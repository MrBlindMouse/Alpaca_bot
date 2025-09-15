import json
import time
import datetime
import math
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests_ratelimiter import LimiterSession
from bs4 import BeautifulSoup
from dotenv import dotenv_values
import traceback, sys, os
import schedule
#import logging

#def exception_handler(exc_type, exc_value, exc_traceback):
#    if issubclass(exc_type, KeyboardInterrupt):
#        sys.__excepthook__(exc_type, exc_value, exc_traceback)
#        return
#    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

#sys.excepthook = handle_uncaught_exception

class Status:
    STATE_FILE = "trading_state.json"

    def __init__(self):
        print("Initializing . . .")
        self.tickers = []
        self.equity = 0
        self.market = "closed"
        self.serverTime = 0
        self.margin = 0

    def check_balances(self, positions, config):
        """Update ticker quantities or liquidate if not found."""
        for item in positions:
            found = False
            for key, ticker in enumerate(self.tickers):
                if ticker["ticker"] == item["symbol"]:
                    found = True
                    if ticker["volume"] != item["qty"]:
                        self.tickers[key]["volume"] = float(item["qty"])
                    break
            if not found:
                print(" "*150, end="\r", flush=True)
                print(f"Liquidating {item['symbol']}")
                close_url = f"{config.urlBase}markets/v2/positions/{item['symbol']}?percentage=100"
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "APCA-API-KEY-ID": config.apiKey,
                    "APCA-API-SECRET-KEY": config.apiSecret
                }
                result = session.delete(close_url, headers=headers)
                if str(result.status_code) == "200":
                    print(f"Liquidating {item['symbol']}; Status: {result.json()['status']}")
                else:
                    print("Liquidation failed:", result.reason, result.text)

    def check_ticker(self, config):
        """Update equity list for NASDAQ100 changes."""
        tickers = find_tickers(config)
        if tickers:
            new_list = [{
                "ticker": item,
                "volume": 0,
                "difference": 0,
                "price": 0,
                "limitTrade": {"open": False, "id": "", "ts": 0}
            } for item in tickers]
            new_list = [
                old_ticker if old_ticker["ticker"] == new_ticker["ticker"] else new_ticker
                for new_ticker in new_list
                for old_ticker in self.tickers
                if old_ticker["ticker"] == new_ticker["ticker"]
            ] or new_list
            self.tickers = new_list
            self.save_state()
            log_post('Tickers updated', config.title, '1')
        else:
            log_post("Tickers not scraped!", config.title, '3')
            time.sleep(5*60)

    def save_state(self):
        with open(self.STATE_FILE, 'w') as file:
            json.dump({
                'tickers': self.tickers,
                'equity': self.equity,
                'market': self.market,
                'serverTime': self.serverTime,
                'margin': self.margin
            }, file)

    def load_state(self):
        if os.path.exists(self.STATE_FILE):
            with open(self.STATE_FILE, 'r') as file:
                state = json.load(file)
                self.tickers = state['tickers']
                self.equity = state['equity']
                self.market = state['market']
                self.serverTime = state['serverTime']
                self.margin = state['margin']
        else:
            print("State file not found")
            raise FileNotFoundError

class Config:
    def update(self):
        config = dotenv_values(".env")
        self.title = "Alpaca Test" if config["VERSION"] == "PAPER" else "Alpaca"
        self.urlBase = "https://paper-api.alpaca." if config["VERSION"] == "PAPER" else "https://api.alpaca."
        self.apiKey = config["PAPER_KEY"] if config["VERSION"] == "PAPER" else config["API_KEY"]
        self.apiSecret = config["PAPER_SECRET"] if config["VERSION"] == "PAPER" else config["API_SECRET"]
        self.margin = float(config["MARGIN"])

def create_session():
    session = LimiterSession(per_minute=200, burst=10)
    retry_strategy = Retry(total=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

def find_tickers(config):
    url = "https://www.slickcharts.com/nasdaq100"
    result = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    tickers = []
    invalid_tickers = set()
    if str(result.status_code) == '200':
        parsed_result = BeautifulSoup(result.content, 'html.parser')
        table_body = parsed_result.find('tbody', id="companyListComponent")
        table_rows = table_body.find_all('tr')
        for line in table_rows:
            table_cell = line.find_all('td')
            if len(table_cell) > 2:
                tickers.append(table_cell[2].text)
        for ticker in tickers[:]:
            asset_url = f"{config.urlBase}markets/v2/assets/{ticker}"
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": config.apiKey,
                "APCA-API-SECRET-KEY": config.apiSecret
            }
            result = session.get(asset_url, headers=headers)
            if str(result.status_code) == '200':
                json_result = result.json()
                if (json_result["tradable"] and json_result["fractionable"] and
                    json_result["status"] == "active" and
                    "ptp_no_exception" not in json_result["attributes"] and
                    "ptp_with_exception" not in json_result["attributes"]):
                    print(" "*150, end="\r", flush=True)
                    print(f"{tickers.index(ticker)}: {ticker} accepted", end="\r", flush=True)
                else:
                    invalid_tickers.add(ticker)
                    print(" "*150, end="\r", flush=True)
                    print(f"Asset profile for {ticker} not favorable")
            else:
                invalid_tickers.add(ticker)
                print(" "*150, end="\r", flush=True)
                print(f"Alpaca API error: {result.reason}")
        return [t for t in tickers if t not in invalid_tickers]
    print(" "*150, end="\r", flush=True)
    print(result.reason)
    return None

def trunc(value, digits):
    x = 10**digits
    return int(value*x)/x

def log_post(snippet, title, code='2'):
    payload = {"code": code, "app": title, "snippet": snippet}
    try:
        result = requests.post("https://www.bmd-studios.com/log", json=payload)
        if result.status_code != 200:
            print(" "*150, end="\r", flush=True)
            print(f"Logging Error: Status code {result.status_code}\n{result.text}\nOriginal exception: {snippet}")
    except Exception as c:
        print(" "*150, end="\r", flush=True)
        print(f"Logging server down: {c}\nOriginal exception: {snippet}")

def bmd_logger(function):
    def exception_handler(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            message = traceback.extract_tb(exc_traceback)
            post_message = f"Exception raised during {function.__name__}<br>"
            for line in message.format():
                post_message += line + '<br>'
            post_message += f"{exc_type}<br>{exc_value}"
            log_post(post_message, config.title, '2')
            time.sleep(10)
    return exception_handler

def create_order(config, volume, direction, symbol, market_status="open", current_price=0, type="value"):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    if market_status == "open":
        payload = {
            "side": direction,
            "type": "market",
            "time_in_force": "day",
            "symbol": symbol,
            "qty" if type == "qty" else "notional": str(volume if type == "qty" else trunc(volume, 2))
        }
    else:
        limit_price = trunc(float(current_price) * (1.005 if direction == "buy" else 0.995), 2)
        payload = {
            "side": direction,
            "type": "limit",
            "limit_price": str(limit_price),
            "time_in_force": "day",
            "symbol": symbol,
            "qty" if type == "qty" else "notional": str(volume if type == "qty" else trunc(volume, 2)),
            "extended_hours": True
        }
    url = f"{config.urlBase}markets/v2/orders"
    response = session.post(url, json=payload, headers=headers)
    if market_status == "open":
        if str(response.status_code) == '200':
            json_response = response.json()
            status = "open"
            timeout = 30
            start_time = time.time()
            while status == "open" and time.time() - start_time < timeout:
                url = f"{config.urlBase}markets/v2/orders/{json_response['id']}"
                response = session.get(url, headers=headers)
                if str(response.status_code) == '200':
                    json_response = response.json()
                    if json_response["status"] in ["filled", "canceled", "expired"]:
                        status = "closed"
                    else:
                        time.sleep(1)
                else:
                    status = "close"
                    print(" "*150, end="\r", flush=True)
                    print(response.reason, response.text)
            return "success" if status == "closed" else "failed"
        print(" "*150, end="\r", flush=True)
        print(response.reason, response.text)
        return "failed"
    if str(response.status_code) == '200':
        return str(response.json()["id"])
    print(" "*150, end="\r", flush=True)
    print(response.reason, response.text)
    return "failed"

def get_account(config):
    url = f"{config.urlBase}markets/v2/account"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    return session.get(url, headers=headers).json()

def get_balances(config, symbol=None):
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    url = f"{config.urlBase}markets/v2/positions{f'/{symbol}' if symbol else ''}"
    response = session.get(url, headers=headers)
    if response.status_code == 200:
        json_response = response.json()
        return float(json_response["qty"]) if symbol else json_response
    print(" "*150, end="\r", flush=True)
    print(f"Error finding {'balance' if symbol else 'balances'}", flush=True)
    print(response.reason, response.text)
    return None

def day_end(account=Status, config=Config):
    if account.market == "holiday":
        return
    balances = get_balances(config)
    base = get_account(config)
    cash = float(base["cash"])
    cost = cash
    equity = cash
    investment = 0
    for entry in balances:
        equity += float(entry["market_value"])
        cost += float(entry["cost_basis"])
    url = f"{config.urlBase}markets/v2/account/activities?activity_types=CSD,CSW&direction=desc&page_size=100"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    response = session.get(url, headers=headers)
    for entry in response.json():
        if entry["activity_type"] == "CSD":
            investment += float(entry["net_amount"])
        elif entry["activity_type"] == "CSW":
            investment -= float(entry["net_amount"])
    url = 'https://www.bmd-studios.com/record'
    payload = {
        "ts": str(int(datetime.datetime.now().timestamp())),
        "equity": trunc(equity, 2),
        "cost": trunc(cost, 2),
        "investment": trunc(investment, 2)
    }
    requests.post(url=url, json=payload)

def check_in(ts, account=Status, config=Config):
    url = 'https://www.bmd-studios.com/bot'
    headers = {"accept": "application/json"}
    payload = {
        "id": "02" if config.title == "Alpaca" else "03",
        "bot_name": config.title,
        "ts": str(ts),
        "status": account.market
    }
    requests.post(url=url, json=payload)
    url = 'https://www.bmd-studios.com/general'
    high_ticker = {"ticker": "", "diff": 0, "val":0}
    low_ticker = {"ticker": "", "diff": 0, "val":0}
    general_swing = 0
    for ticker in account.tickers:
        general_swing += ticker["difference"]
        if high_ticker["val"] == 0 or (ticker["volume"]*ticker["price"]) > high_ticker["val"]:
            high_ticker["ticker"] = ticker["ticker"]
            high_ticker["diff"] = ticker["difference"]
            high_ticker["val"] = ticker["volume"]*ticker["price"]

        if low_ticker["val"] == 0 or (ticker["volume"]*ticker["price"]) < low_ticker["val"]:
            low_ticker["ticker"] = ticker["ticker"]
            low_ticker["diff"] = ticker["difference"]
            low_ticker["val"] = ticker["volume"]*ticker["price"]


    general_swing = general_swing/len(account.tickers)
    balance_value = account.equity / (len(account.tickers)*(1+account.margin))
    time = datetime.datetime.now()
    display_str = f"""
    <div style="padding:5px;">
    <p>{time}</p>
    <p>Highest Swing: {high_ticker["ticker"]}: {trunc(high_ticker["diff"]*100, 1)}% at ${trunc(high_ticker["val"],2)}</p>
    <p>Lowest Swing: {low_ticker["ticker"]}: {trunc(low_ticker["diff"]*100, 1)}% at ${trunc(low_ticker["val"],2)}</p>
    <p>Avg Swing size: {trunc(general_swing*100, 1)}% for {len(account.tickers)} tickers balancing to ${trunc(balance_value,2)}.</p>
    </div>
    """
    payload = {
        "id": "02",
        "ts": str(ts),
        "name": "Alpaca",
        "json_string": display_str
    }
    requests.post(url=url, json=payload)

def check_balances(account=Status, config=Config):
    if account.market not in ["closed", "holiday"]:
        positions = get_balances(config)
        account.check_balances(positions, config)

def check_time(account=Status, config=Config):
    global server
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    url = f"{config.urlBase}markets/v2/clock"
    result = session.get(url, headers=headers)
    if result.status_code == 200:
        json_result = result.json()
        time_string = json_result["timestamp"][:19] + json_result["timestamp"][-6:]
        dt_object = datetime.datetime.strptime(time_string, "%Y-%m-%dT%H:%M:%S%z")
        account.serverTime = int(dt_object.timestamp())
        if json_result["is_open"]:
            if server != "open":
                print(" "*150, end="\r", flush=True)
                print("Updating Equity List . . .")
                account.check_ticker(config)
                server = "open"
            if account.market == "extended":
                print(" "*150, end="\r", flush=True)
                print(f"Trade start for {dt_object.year}-{dt_object.month}-{dt_object.day}", flush=True)
            account.market = "open"
        elif 4 <= int(dt_object.hour) < 20:
            if server != "closed":
                server = "closed"
            if account.market == "closed":
                print(" "*150, end="\r", flush=True)
                print(f"Checking if {dt_object.year}-{dt_object.month}-{dt_object.day} is a holiday", end="\r", flush=True)
                start_date = f"start={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
                end_date = f"end={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
                url = f"{config.urlBase}markets/v2/calendar?{start_date}&{end_date}"
                result = session.get(url, headers=headers)
                if str(result.status_code) == '200':
                    json_result = result.json()
                    if len(json_result) < 1:
                        print(" "*150, end="\r", flush=True)
                        print(f"{dt_object.hour}:{dt_object.minute} ~ Market closed for the day", flush=True)
                        account.market = "holiday"
                        account.save_state()
                        check_in(int(time.time()), account, config)
                        time.sleep(61200)
                    else:
                        print(" "*150, end="\r", flush=True)
                        print(f"Extended Hours Trade start for {dt_object.year}-{dt_object.month}-{dt_object.day}", flush=True)
                        account.market = "extended"
                else:
                    print(" "*150, end="\r", flush=True)
                    print(result.reason, result.text)
            elif account.market == "open":
                print(" "*150, end="\r", flush=True)
                print("Market Closed, Extended Hours Trade until 20:00", flush=True)
                account.market = "extended"
        else:
            if server != "closed":
                server = "closed"
            if account.market == "closed":
                print(" "*150, end="\r", flush=True)
                print(f"{dt_object.hour}:{dt_object.minute}:{dt_object.second} ~ Market Closed, Equity: ${account.equity}", end="\r", flush=True)
            else:
                account.market = "closed"
    else:
        log_post(f'Error finding server time:<br> {result.text}', config.title)
        print(" "*150, end="\r", flush=True)
        print("Error finding Server Time", result.reason, result.text)

def bot(account=Status, config=Config):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    dt_object = datetime.datetime.fromtimestamp(account.serverTime, datetime.timezone.utc)
    high_ticker = {"ticker": "", "diff": 0}
    if account.equity == 0:
        print(" "*150, end="\r", flush=True)
        print("Loading Alpaca Account data")
        account_data = get_account(config)
        account.equity = float(account_data["equity"])
        print("Updating Tickers")
        account.check_ticker(config)
        print("Finding open limit orders")
        orders_url = f"{config.urlBase}markets/v2/orders"
        result = session.get(orders_url, headers=headers)
        if result.status_code == 200:
            for item in result.json():
                for key, ticker in enumerate(account.tickers):
                    if item["symbol"] == ticker["ticker"] and not ticker["limitTrade"]["open"]:
                        account.tickers[key]["limitTrade"] = {"open": True, "id": item["id"], "ts": 0}
                        break
    if account.market not in ["closed", "holiday"]:
        account_data = get_account(config)
        total_pos = len(account.tickers)
        account.equity = float(account_data["equity"])
        base_balance = account.equity / (total_pos + (total_pos * account.margin))
        ticker_list = [ticker["ticker"] for ticker in account.tickers]
        tickers_str = "%2C".join(ticker_list)
        snapshot_url = f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={tickers_str}&feed=iex"
        result = session.get(snapshot_url, headers=headers)
        if result.status_code == 200:
            json_result = result.json()
            for key, ticker in enumerate(account.tickers):
                if ticker["ticker"] in json_result and json_result[ticker["ticker"]].get("minuteBar"):
                    account.tickers[key]["price"] = float(json_result[ticker["ticker"]]["minuteBar"]["vw"])
                else:
                    print(" "*150, end="\r", flush=True)
                    print(f"No snapshot data for {ticker['ticker']}")
        else:
            log_post(f"Error calling new snapshot:<br>{result.text}", config.title)
            print(" "*150, end="\r", flush=True)
            print(f"Error calling new snapshot: {result.status_code} {result.reason} {result.text}")
        for key, ticker in enumerate(account.tickers):
            balance_value = base_balance
            if ticker["limitTrade"]["open"]:
                open_url = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
                result = session.get(open_url, headers=headers)
                if str(result.status_code) == "200":
                    json_result = result.json()
                    if json_result["status"] in ["filled", "canceled", "expired"]:
                        account.tickers[key]["limitTrade"] = {"open": False, "id": "", "ts": account.serverTime}
                        new_volume = get_balances(config, ticker["ticker"])
                        if new_volume and new_volume != ticker["volume"]:
                            account.tickers[key]["volume"] = new_volume
                    elif (account.serverTime - ticker["limitTrade"]["ts"]) > 300:
                        delete_url = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
                        result = session.delete(delete_url, headers=headers)
                        print(" "*150, end="\r", flush=True)
                        print("Cancelled old limit order" if str(result.status_code) == "204" else
                              f"Failed to cancel old limit order: {result.status_code} {result.reason} {result.text}")
                        account.tickers[key]["limitTrade"] = {"open": False, "id": "", "ts": account.serverTime}
                        new_volume = get_balances(config, ticker["ticker"])
                        if new_volume and new_volume != ticker["volume"]:
                            account.tickers[key]["volume"] = new_volume
                else:
                    print(" "*150, end="\r", flush=True)
                    print(f"Failed to check open order: {ticker['limitTrade']['id']} {result.reason} {result.text}")
                    account.tickers[key]["limitTrade"] = {"open": False, "id": "", "ts": account.serverTime}
                    new_volume = get_balances(config, ticker["ticker"])
                    if new_volume and new_volume != ticker["volume"]:
                        account.tickers[key]["volume"] = new_volume
            if ticker["volume"] == 0 and not ticker["limitTrade"]["open"]:
                result = create_order(config, balance_value, "buy", ticker["ticker"], account.market, ticker["price"], "value")
                print(" "*150, end="\r", flush=True)
                print(f"Buying initial {ticker['ticker']} shares", flush=True)
                if result == "success":
                    print(f"Bought ${balance_value} of {ticker['ticker']}")
                    new_volume = get_balances(config, ticker["ticker"])
                    if new_volume and new_volume != ticker["volume"]:
                        account.tickers[key]["volume"] = new_volume
                elif result == "failed":
                    print(f"Failed to buy ${balance_value} of {ticker['ticker']}")
                else:
                    print(f"Placed limit order to buy ${balance_value} of {ticker['ticker']}")
                    account.tickers[key]["limitTrade"] = {"open": True, "id": result, "ts": account.serverTime}
            if not ticker["limitTrade"]["open"]:
                current_value = ticker["volume"] * ticker["price"]
                if current_value > balance_value:
                    diff = (current_value - balance_value) / balance_value
                    if diff < account.margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif diff < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2))) and diff > account.margin:
                        sell_value = current_value - balance_value
                        result = create_order(config, sell_value, "sell", ticker["ticker"], account.market, ticker["price"], "value")
                        print(" "*150, end="\r", flush=True)
                        if result == "success":
                            print(f"Sold ${sell_value} of {ticker['ticker']}", flush=True)
                            new_volume = get_balances(config, ticker["ticker"])
                            if new_volume:
                                account.tickers[key]["volume"] = new_volume
                        elif result == "failed":
                            print(f"Failed to sell ${sell_value} of {ticker['ticker']}")
                        else:
                            print(f"Placed limit order to sell ${sell_value} of {ticker['ticker']}")
                            account.tickers[key]["limitTrade"] = {"open": True, "id": result, "ts": account.serverTime}
                elif current_value < balance_value:
                    diff = (balance_value - current_value) / balance_value
                    if diff < account.margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif diff < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2))) and diff > account.margin:
                        buy_value = balance_value - current_value
                        result = create_order(config, buy_value, "buy", ticker["ticker"], account.market, ticker["price"], "value")
                        print(" "*150, end="\r", flush=True)
                        if result == "success":
                            print(f"Bought ${buy_value} of {ticker['ticker']}", flush=True)
                            new_volume = get_balances(config, ticker["ticker"])
                            if new_volume:
                                account.tickers[key]["volume"] = new_volume
                        elif result == "failed":
                            print(f"Failed to buy ${buy_value} of {ticker['ticker']}")
                        else:
                            print(f"Placed limit order to buy ${buy_value} of {ticker['ticker']}")
                            account.tickers[key]["limitTrade"] = {"open": True, "id": result, "ts": account.serverTime}
                else:
                    account.tickers[key]["difference"] = 0
            if ticker["difference"] > high_ticker["diff"]:
                high_ticker["diff"] = ticker["difference"]
                high_ticker["ticker"] = ticker["ticker"]
        print(" "*150, end="\r", flush=True)
        print(f"{dt_object.hour}:{dt_object.minute}:{dt_object.second} ~ '{account.market.upper()}' trade, "
              f"Equity: ${account.equity}; Highest Swing {high_ticker['ticker']}:{trunc(high_ticker['diff']*100, 1)}% "
              f"Balance Value: ${trunc(base_balance, 2)}", end="\r", flush=True)
    else:
        print(" "*150, end="\r", flush=True)
        print(f"{dt_object.hour}:{dt_object.minute}:{dt_object.second} ~ '{account.market.upper()}' trade, "
              f"Equity: ${account.equity}; Highest Swing {high_ticker['ticker']}:{trunc(high_ticker['diff']*100, 1)}% "
              f"Balance Value: ${trunc(base_balance, 2)}", end="\r", flush=True)

@bmd_logger
def bot_loop(account=Status, config=Config):
    config.update()
    account.margin = config.margin
    check_time(account, config)
    if account.market in ['open','extended']:
        bot(account, config)
    account.save_state()
    check_in(int(time.time()), account, config)

session = create_session()
server = "closed"

if __name__ == "__main__":
    account = Status()
    try:
        print("Loading account . . .")
        account.load_state()
    except Exception as e:
        account.save_state()
    config = Config()
    schedule.every(1).minute.do(bot_loop, account=account, config=config)
    schedule.every(1).hour.do(check_balances, account=account, config=config)
    schedule.every().day.at("22:00").do(day_end, account=account, config=config)
    while True:
        try:
            schedule.run_pending()
            time.sleep(5)
        except Exception as e:
            account.load_state()
            raise
