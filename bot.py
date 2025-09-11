from dotenv import dotenv_values
import requests, json, time, datetime, math
import traceback, sys, os
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests_ratelimiter import LimiterSession
import pickle
import schedule
import indicators


class Status():
    STATE_FILE = "trading_state.pkl"
    def __init__(self):
        print("Initializing . . .")
        self.tickers = []
        self.equity = 0
        self.market = "closed"
        self.serverTime = 0
        self.margin = 0

    def check_balances(self, positions, config):
        "Updating Ticker qty, or liquidating if not found"
        for item in positions:
            found = False
            for key,ticker in enumerate(self.tickers):
                if ticker["ticker"] == item["symbol"]:
                    found = True
                    if ticker["volume"] != item["qty"]:
                        self.tickers[key]["volume"] = float(item["qty"])
                    break
            if not found:
                print(" "*150, end="\r", flush=True)
                print("Liquidating {}".format(item["symbol"]))
                closeURL = "{}markets/v2/positions/{}?percentage=100".format(config.urlBase,item["symbol"])
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "APCA-API-KEY-ID": config.apiKey,
                    "APCA-API-SECRET-KEY": config.apiSecret
                }
                result = session.delete(closeURL,headers=headers)
                if str(result.status_code) == "200":
                    jsonResult = result.json()
                    print("Liquidating {}; Status: {}".format(item["symbol"],jsonResult["status"]))
                else:
                    print("Liquidation failed")
                    print(result.reason)
                    print(result.text)

    def check_ticker(self,config):
        """
        Check and update equity list for changes in NASDAQ100
        """
        tickers = find_tickers(config)
        if tickers:
            new_list = []
            for item in tickers:
                new_list.append({
                    "ticker":item,
                    "volume":0,
                    "difference":0,
                    "price":0,
                    "limitTrade":{
                        "open":False,
                        "id":"",
                        "ts":0,
                    },
                    "beta":1,
                    "rsi":50,
                    "trend":1
                })
            for key, new_ticker in enumerate(new_list):         #Add Liquidate if old ticker not found
                for old_ticker in self.tickers:
                    if old_ticker["ticker"] == new_ticker["ticker"]:
                        new_list[key] = old_ticker
            print("Updateting Trends")
            trendList = indicators.trend(tickers, config, session)
            for key, value in enumerate(new_list):
                for entry in trendList:
                    if new_list[key]["ticker"] == entry["ticker"]:
                        new_list[key]["rsi"] = entry["rsi"]
                        new_list[key]["trend"] = entry["trend"]
            currentTS = int(time.time())
            print("Updateting Beta")
            betaList = indicators.beta(tickers, config, session)
            self.betaTS = currentTS
            for key, value in enumerate(new_list):
                for entry in betaList:
                    if new_list[key]["ticker"] == entry["ticker"]:
                        new_list[key]["beta"] = entry["beta"]
            
            self.tickers = new_list
            self.save_state()
            generalTrend = 0
            for item in self.tickers:
                generalTrend += ((item["rsi"]/50)+item["trend"])/2
            generalTrend = generalTrend/len(self.tickers)
            logPost(f'General Market Trend: {generalTrend:3f}', config.title, '1')
        else:
            logPost("Tickers not scraped!", config.title, '3')
            time.sleep(5*60)

    def save_state(self):
        with open(self.STATE_FILE, 'wb') as file:
            pickle.dump({
                'tickers':self.tickers,
                'equity':self.equity,
                'market':self.market,
                'serverTime':self.serverTime,
                'margin':self.margin
            }, file)
    
    def load_state(self):
        if os.path.exists(self.STATE_FILE):
            with open(self.STATE_FILE, 'rb') as file:
                state = pickle.load(file)
                self.tickers = state['tickers']
                self.equity = state['equity']
                self.market = state['market']
                self.serverTime = state['serverTime']
                self.margin = state['margin']
        else:
            print("State file not found")
            raise

class Config():
    def update(self):
        config = dotenv_values(".env")
        self.title = "Alpaca Test" if config["VERSION"] == "PAPER" else "Alpaca"
        self.urlBase = "https://paper-api.alpaca." if config["VERSION"] == "PAPER" else "https://api.alpaca."
        self.apiKey = config["PAPER_KEY"] if config["VERSION"] == "PAPER" else config["API_KEY"]
        self.apiSecret = config["PAPER_SECRET"] if config["VERSION"] == "PAPER" else config["API_SECRET"]
        self.margin = float(config["MARGIN"])
        self.dynamicMargin = True if config["DYNAMIC_MARGIN"] == "True" else False
        self.weightRefinement = True if config["WEIGHT_REFINEMENT"] == "True" else False

def create_session():
    session = LimiterSession(per_minute=200, burst=10)
    retry_strategy = Retry(
        total=3,
        backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

def find_tickers(config):
    url = "https://www.nasdaq.com/solutions/global-indexes/nasdaq-100/companies"
    result = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    tickers = []
    if str(result.status_code) == '200':
        parsed_result = BeautifulSoup(result.content, 'html.parser')
        tables = parsed_result.find_all('tbody')
        for table in tables:
            rows = table.find_all('tr')
            data = rows[0].find_all('td')
            if data[0].text == "Symbol" and data[1].text == "Company Name":
                for entry in rows[1:]:
                    tickers.append(entry.find_all('td')[0].text)
            if len(tickers) > 0:
                break
        for key, ticker in enumerate(tickers):
            assetURL = "{}markets/v2/assets/{}".format(config.urlBase, ticker)
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": config.apiKey,
                "APCA-API-SECRET-KEY": config.apiSecret
            }
            result = session.get(assetURL, headers=headers)

            #Alpaca rate limit
            time.sleep(0.4)

            if str(result.status_code) == '200':
                jsonResult = result.json()
                if bool(jsonResult["tradable"]) and bool(jsonResult["fractionable"]) and jsonResult["status"] == "active" and "ptp_no_exception" not in jsonResult["attributes"] and "ptp_with_exception" not in jsonResult["attributes"]:
                    print(" "*150, end="\r", flush=True)
                    print("{}: {} accepted".format(key,ticker), end="\r", flush=True)
                else:
                    tickers.pop(key)
                    print("Asset profile for {} nor favourable".format(ticker))

            else:
                tickers.pop(key)
                print("Alpaca API error: {}".format(result.reason))
                print(assetURL)
                print(json.dumps(header, indent=4))
    else:
        print(result.reason)
    return tickers

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x


def logPost(snippet, title, code='2'):
    """
    Code '1': Info
    Code '2': Error
    Code '3': Emergency
    """
    payload = {
        "code": code,
        "app": title,
        "snippet": snippet
    }
    try:
        result = requests.post("https://www.bmd-studios.com/log", json=payload)
        if result.status_code != 200:
            print(" "*150, end="\r", flush=True)
            print("Logging Error")
            print("Status code: "+str(result.status_code))
            print(result.text)
            print('Original exception: ')
            print(snippet)
    except Exception as c:
        print(" "*150, end="\r", flush=True)
        print("Logging server down . . .")
        print(str(c))
        print('Original exception: ')
        print(snippet)

def bmd_logger(function):
    def exception_handler(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            print(" "*150, end="\r", flush=True)
            print(str(datetime.datetime.today())+" ~ Exception raised during "+function.__name__, flush=True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            message = traceback.extract_tb(exc_traceback)
            post_message = "Exception raised during "+function.__name__+'<br>'
            for line in message.format():
                post_message += line+'<br>'
            post_message += str(exc_type)+'\n<br>'+str(exc_value)
            logPost(post_message, config.title, '2')
            time.sleep(10)
    return exception_handler

def create_order(config, volume, direction, symbol, marketStatus="open", currentPrice=0, type="value"):
    """
    If type = 'qty' then volume = number of stocks
    if type = 'value' then volume = value of shares
    currentPrice required if marketStatus != 'open'
    marketStatus required if not 'open'
    Returns 'success' upon market trade success
    Returns 'failed' upon trade failure
    Returns trade id upon limit trade success
    """

    if marketStatus == "open":
        if type == "qty":
            payload = {
                "side":direction,
                "type":"market",
                "time_in_force":"day",
                "symbol":symbol,
                "qty": str(volume),
            }
        else:
            payload = {
                "side":direction,
                "type":"market",
                "time_in_force":"day",
                "symbol":symbol,
                "notional": str(trunc(volume,2)),
            }
    else:
        limitPrice = 0
        if direction == "buy":
            limitPrice = trunc(float(currentPrice)*1.005,2)
        elif direction == "sell":
            limitPrice = trunc(float(currentPrice)*.995,2)
        if type == "qty":
            payload = {
                "side":direction,
                "type":"limit",
                "limit_price":str(limitPrice),
                "time_in_force":"day",
                "symbol":symbol,
                "qty": str(volume),
                "extended_hours":True,
            }
        else:
            payload = {
                "side":direction,
                "type":"limit",
                "limit_price":str(limitPrice),
                "time_in_force":"day",
                "symbol":symbol,
                "notional": str(trunc(volume,2)),
                "extended_hours":True,
            }

    url="{}markets/v2/orders".format(config.urlBase)
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    response = session.post(url, json=payload, headers=headers)
    if marketStatus == "open":
        if str(response.status_code) == '200':
            json_response = response.json()
            status = "open"
            while status == "open":
                url = "{}markets/v2/orders/{}".format(config.urlBase,str(json_response["id"]))
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "APCA-API-KEY-ID": config.apiKey,
                    "APCA-API-SECRET-KEY": config.apiSecret
                }
                response = session.get(url, headers=headers)
                if str(response.status_code) == '200':
                    json_response = response.json()
                    if json_response["status"] == "filled" or json_response["status"] == "canceled" or json_response["status"] == "expired":
                        status = "closed"
                    else:
                        time.sleep(1)
                else:
                    status = "close"
                    print(" "*150, end="\r", flush=True)
                    print(response.reason)
                    print(response.text)
            return "success"
        else:
            print(" "*150, end="\r", flush=True)
            print(response.reason)
            print(response.text)
            return "failed"
    else:
        if str(response.status_code) == '200':
            json_response = response.json()
            return str(json_response["id"])
        else:
            print(" "*150, end="\r", flush=True)
            print(response.reason)
            print(response.text)
            return "failed"

def get_account(config):
    "Returns account info"
    url = "{}markets/v2/account".format(config.urlBase)
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    response = session.get(url, headers=headers)
    json_response = response.json()
    return json_response

def get_balances(config, symbol=None):
    """
    Return positions of given symbol, or all symbols if none supplied
    """
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    if symbol:
        url = f"{config.urlBase}markets/v2/positions/{symbol}"

        response = session.get(url, headers=headers)
        if response.status_code == 200:
            json_response = response.json()
            return float(json_response["qty"])
        else:
            print(" "*150, end="\r", flush=True)
            print(f"Error finding {symbol} balance", flush=True)
            print(response.reason)
            print(response.text)
            return None
    else:
        url = f"{config.urlBase}markets/v2/positions"

        response = session.get(url, headers=headers)
        if response.status_code == 200:
            json_response = response.json()
            return json_response
        else:
            print(" "*150, end="\r", flush=True)
            print("Error finding balances", flush=True)
            print(response.reason)
            print(response.text)
            return None

def day_end(account=Status, config=Config):
    if account.market == "holiday":
        return
    balances = get_balances()
    base = get_account()
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
    json_response = response.json()
    for entry in json_response:
        if entry["activity_type"] == "CSD":
            investment += float(entry["net_amount"])
        elif entry["activity_type"] == "CSW":
            investment -= float(entry["net_amount"])
    

    url = 'https://www.bmd-studios.com/record'
    headers = {
        "accept": "application/json"
    }
    payload={
        "ts":str(int(datetime.datetime.now().timestamp())),
        "equity":trunc(equity,2),
        "cost":trunc(cost,2),
        "investment":trunc(investment,2)
    }
    requests.post(url=url,json=payload)

def checkIn(ts, account=Status, config=Config):
    """
    Basic Check In to BMD
    """
    url = 'https://www.bmd-studios.com/bot'
    headers = {
        "accept": "application/json"
    }
    payload={
        "id":"03",
        "bot_name":config.title,
        "ts":str(ts),
        "status":account.market
    }
    if config.title == 'Alpaca':
        payload["id"] = '02'
    requests.post(url=url,json=payload)

    url = 'https://www.bmd-studios.com/general'
    
    marketTrend = 0
    marketRSI = 0
    for ticker in account.tickers:
        marketTrend += ticker["trend"]
        marketRSI += ticker["rsi"]
    marketTrend = marketTrend/len(account.tickers)
    marketRSI = marketRSI/len(account.tickers)
    generalTrend = (marketTrend+(marketRSI/50))/2

    highTicker = {
        "ticker":"",
        "diff":0
    }
    secondTicker = {
        "ticker":"",
        "diff":0
    }
    for ticker in account.tickers:
        if ticker["difference"] > highTicker["diff"]:
            secondTicker["diff"] = highTicker["diff"]
            secondTicker["ticker"] = highTicker["ticker"]
            highTicker["diff"] = ticker["difference"]
            highTicker["ticker"] = ticker["ticker"]
        elif ticker["difference"] > secondTicker["diff"]:
            secondTicker["diff"] = ticker["difference"]
            secondTicker["ticker"] = ticker["ticker"]

    displayStr = f"""
    <p>Current Trend: {generalTrend}</p>
    <p>Highest Swing: {highTicker["ticker"]}:{trunc(highTicker["diff"]*100,1)}%</p>
    <p>Second Swing: {secondTicker["ticker"]}:{trunc(secondTicker["diff"]*100,1)}%</p>
    """
    payload={
        "id":"02",
        "ts":str(ts),
        "name":"Alpaca",
        "json_string":displayStr
    }
    requests.post(url=url,json=payload)

def checkBalances(account=Status, config=Config):
    if account.market not in ["closed","holiday","suspended"]:
        positions = get_balances(config)
        account.check_balances(positions, config)
    elif account.market == "suspended":
        positions = get_balances(config)
        for item in positions:
            print(" "*150, end="\r", flush=True)
            print(f"Liquidating {item["symbol"]}")
            closeURL = f"{config.urlBase}markets/v2/positions/{item["symbol"]}?percentage=100"
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": config.apiKey,
                "APCA-API-SECRET-KEY": config.apiSecret
            }
            result = session.delete(closeURL,headers=headers)
            if result.status_code == 200:
                jsonResult = result.json()
                print(f"Status: {jsonResult["status"]}")
            else:
                print(f"Liquidation failed")
                print(result.reason)
                print(result.text)

def checkTime(account=Status, config=Config, server="closed"):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    
    url = "{}markets/v2/clock".format(config.urlBase)
    result = session.get(url, headers=headers)
    if result.status_code == 200:
        jsonResult = result.json()
        time_string = jsonResult["timestamp"]
        time_string = time_string[:19]+time_string[-6:]
        dt_object = datetime.datetime.strptime(time_string,"%Y-%m-%dT%H:%M:%S%z")
        account.serverTime = int(dt_object.timestamp())



        if jsonResult["is_open"]:
            if server != "open":
                print("Updateting Equity List . . .")
                account.check_ticker(config)
                server = "open"

            if account.market == "extended":
                print(" "*150, end="\r", flush=True)
                print("Trade start for {}-{}-{}".format(str(dt_object.year),str(dt_object.month),str(dt_object.day)), flush=True)
                
            if account.market != "suspended":
                marketTrend = 0
                marketRSI = 0
                for ticker in account.tickers:
                    marketTrend += ticker["trend"]
                    marketRSI += ticker["rsi"]
                marketTrend = marketTrend/len(account.tickers)
                marketRSI = marketRSI/len(account.tickers)
                generalTrend = (marketTrend+((marketRSI/100)+0.5))/2
                if generalTrend < 0.85:
                    account.market = "suspended"
                else:
                    account.market = "open"
            else:
                marketTrend = 0
                marketRSI = 0
                for ticker in account.tickers:
                    marketTrend += ticker["trend"]
                    marketRSI += ticker["rsi"]
                marketTrend = marketTrend/len(account.tickers)
                marketRSI = marketRSI/len(account.tickers)
                generalTrend = (marketTrend+((marketRSI/100)+0.5))/2
                if generalTrend > 0.95:
                    account.market = "open"

        elif int(dt_object.hour) >= 4 and int(dt_object.hour) < 20 and account.market!="suspended":
            if server!="closed":
                server="closed"
            if account.market == "closed":
                print(" "*150, end="\r", flush=True)
                print("Checking if {}-{}-{} is a holiday".format(str(dt_object.year),str(dt_object.month),str(dt_object.day)),end="\r", flush=True)
                startDate = "start={}-{}-{} 00:00:00".format(str(dt_object.year), str(dt_object.month), str(dt_object.day))
                endDate = "end={}-{}-{} 00:00:00".format(str(dt_object.year), str(dt_object.month), str(dt_object.day))
                url = "{}markets/v2/calendar?{}&{}".format(config.urlBase,startDate,endDate)
                result = session.get(url, headers=headers)
                if str(result.status_code) == '200':
                    jsonResult = result.json()
                    if len(jsonResult) < 1:
                        print(" "*150, end="\r", flush=True)
                        print("{}:{} ~ Market closed for the day".format(str(dt_object.hour),str(dt_object.minute)), flush=True)
                        account.market = "holiday"
                        account.save_state()
                        checkIn(int(time.time()), account, config)
                        time.sleep(61200)
                    else:
                        print(" "*150, end="\r", flush=True)
                        print("Extended Hours Trade start for {}-{}-{}".format(str(dt_object.year),str(dt_object.month),str(dt_object.day)), flush=True)
                        account.market = "extended"

                else:
                    print(" "*150, end="\r", flush=True)
                    print(result.reason)
                    print(result.text)
            elif account.market == "open":
                print(" "*150, end="\r", flush=True)
                print("Market Closed, Extended Hours Trade untill 20:00", flush=True)
                account.market = "extended"

        else:
            if server!="closed":
                server="closed"

            if account.market == "closed":
                print(" "*150, end="\r", flush=True)
                print("{}:{}:{} ~ Market Closed, Equity: ${}".format(dt_object.hour,dt_object.minute,dt_object.second, str(account.equity)), end="\r", flush=True)
            elif account.market!="suspended":
                account.market = "closed"
                
    else:
        logPost(f'Error finding server time:<br> {result.text}')
        print(" "*150, end="\r", flush=True)
        print("Error finding Server Time", flush=True)
        print(result.reason)
        print(result.text)

def bot(account=Status, config=Config):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }

    if account.equity == 0:
        print("Loading Alpaca Account data")
        accountData = get_account(config)
        account.equity = float(accountData["equity"])
        print("Updating Tickers")
        account.check_ticker(config)
        print("Finding open limit orders")
        ordersURL = f"{config.urlBase}markets/v2/orders" # Finding un-recorded open limit orders
        result = session.get(ordersURL, headers=headers)
        if result.status_code == 200:
            jsonResult = result.json()
            for item in jsonResult:
                for key,ticker in enumerate(account.tickers):
                    if item["symbol"] == ticker["ticker"]:
                        if not ticker["limitTrade"]["open"]:
                            account.tickers[key]['limitTrade']["open"] = True
                            account.tickers[key]['limitTrade']["id"] = item["id"]
                            account.tickers[key]['limitTrade']["ts"] = 0
                        break

    if account.market not in ["closed","holiday","suspended"]:
        accountData = get_account(config)
        total_pos = len(account.tickers)
        account.equity = float(accountData["equity"])
        baseBalance = account.equity/(total_pos+(total_pos*account.margin))

        ticker_list = []
        for ticker in account.tickers:
            ticker_list.append(ticker["ticker"])
        tickersStr = "%2C".join(ticker_list)
        snapshotURL = "https://data.alpaca.markets/v2/stocks/snapshots?symbols={}&feed=iex".format(tickersStr)
        result = session.get(snapshotURL, headers=headers)
        if result.status_code == 200:
            jsonResult = result.json()
            for key,ticker in enumerate(account.tickers):
                account.tickers[key]["price"] = float(jsonResult[ticker["ticker"]]["minuteBar"]["vw"])
        else:
            logPost(f"Error call new snapshot:<br>{result.text}")
            print("Error calling new snapshot")
            print(str(result.status_code))
            print(result.reason)
            print(result.text)
        
        marketTrend = 0
        marketRSI = 0
        for ticker in account.tickers:
            marketTrend += ticker["trend"]
            marketRSI += ticker["rsi"]
        marketTrend = marketTrend/len(account.tickers)
        marketRSI = marketRSI/len(account.tickers)
        generalTrend = (marketTrend+(marketRSI/50))/2

        for key, ticker in enumerate(account.tickers):
            weight = 1+(5*((generalTrend-1)**2)*(abs(generalTrend-1)/(generalTrend-1)))
            weight = max(0, min(1, weight)) #Adjustment capped at 100% during downwards trend
            balance_value = baseBalance*weight if config.weightRefinement else baseBalance
            

            if ticker["limitTrade"]["open"]:    #Checking open limit orders
                openURL = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
                result = session.get(openURL, headers=headers)
                if str(result.status_code) == "200":
                    jsonResult = result.json()
                    if jsonResult["status"] == "filled" or jsonResult["status"] == "canceled" or jsonResult["status"] == "expired":
                        account.tickers[key]["limitTrade"]["open"] = False
                        account.tickers[key]["limitTrade"]["id"] = ""
                        account.tickers[key]["limitTrade"]["ts"] = account.serverTime
                        newVolume = get_balances(config,ticker["ticker"])
                        if newVolume and newVolume != ticker["volume"]:
                            account.tickers[key]["volume"] = newVolume
                    elif (account.serverTime - ticker["limitTrade"]["ts"]) > 300:    #Removing old limit orders
                        deleteURL = "{}markets/v2/orders/{}".format(config.urlBase,ticker["limitTrade"]["id"])
                        result = session.delete(deleteURL, headers=headers)
                        print(" "*150, end="\r", flush=True)
                        if str(result.status_code) == "204":
                            print("Cancelled old limit order")
                        else:
                            print("Failed to cancel old limit order", flush=True)
                            print(str(result.status_code))
                            print(result.reason)
                            print(result.text)
                        account.tickers[key]["limitTrade"]["open"] = False
                        account.tickers[key]["limitTrade"]["id"] = ""
                        account.tickers[key]["limitTrade"]["ts"] = account.serverTime
                else:
                    print(" "*150, end="\r", flush=True)
                    print("Failed to check open order: {}".format(ticker["limitTrade"]["id"]))
                    print(result.reason)
                    print(result.text)
                    account.tickers[key]["limitTrade"]["open"] = False
                    account.tickers[key]["limitTrade"]["id"] = ""
                    account.tickers[key]["limitTrade"]["ts"] = account.serverTime
                    newVolume = get_balances(config,ticker["ticker"])
                    if newVolume and newVolume != ticker["volume"]:
                        account.tickers[key]["volume"] = newVolume

            if ticker["volume"] == 0 and not ticker["limitTrade"]["open"]:   #Buy initial shares
                result = create_order(config,balance_value,"buy",ticker["ticker"],account.market,ticker["price"],"value")
                print(" "*150, end="\r", flush=True)
                print("Buyinf initial {} shares".format(ticker["ticker"]), flush=True)
                if result == "success":
                    print("Bought ${} of {}".format(balance_value,ticker["ticker"]), )
                    newVolume = get_balances(config,ticker["ticker"])
                    if newVolume and newVolume != ticker["volume"]:
                        account.tickers[key]["volume"] = newVolume
                elif result == "failed":
                    print("Failed to buy ${} of {}".format(balance_value,ticker["ticker"]), )
                else:
                    print("Place limit order to buy ${} of {}".format(balance_value,ticker["ticker"]), )
                    account.tickers[key]["limitTrade"]["open"] = True
                    account.tickers[key]["limitTrade"]["id"] = result
                    account.tickers[key]["limitTrade"]["ts"] = account.serverTime

            if not ticker["limitTrade"]["open"]:    #Balance ticker if no limit trade open
                if (ticker["volume"]*ticker["price"]) > balance_value:
                    diff = ((ticker["volume"]*ticker["price"])-balance_value)/balance_value
                    if diff < margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif diff < (ticker["difference"]*(1-((ticker["difference"]+margin)/2))) and diff > margin:
                        sell_value = (ticker["volume"]*ticker["price"])-balance_value
                        result = create_order(config,sell_value,"sell",ticker["ticker"],account.market,ticker["price"],"value")
                        print(" "*150, end="\r", flush=True)
                        if result == "success":
                            print("Sold ${} of {}".format(str(sell_value),ticker["ticker"]), flush=True)
                            newVolume = get_balances(config,ticker["ticker"])
                            if newVolume:
                                account.tickers[key]["volume"] = newVolume
                        elif result == "failed":
                            print("Failed to sell ${} of {}".format(str(sell_value),ticker["ticker"]))
                        else:
                            print("Place limit order to sell ${} of {}".format(str(sell_value),ticker["ticker"]))
                            account.tickers[key]["limitTrade"]["open"] = True
                            account.tickers[key]["limitTrade"]["id"] = result
                            account.tickers[key]["limitTrade"]["ts"] = account.serverTime


                elif (ticker["volume"]*ticker["price"]) < balance_value:
                    diff = (balance_value-(ticker["volume"]*ticker["price"]))/balance_value
                    if diff < margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif diff < (ticker["difference"]*(1-((ticker["difference"]+margin)/2))) and diff > margin:
                        buy_value = (balance_value-(ticker["volume"]*ticker["price"]))
                        result = create_order(config,buy_value,"buy",ticker["ticker"],account.market,ticker["price"],"value")
                        print(" "*150, end="\r", flush=True)
                        if result == "success":
                            print("Bought ${} of {}".format(str(buy_value),ticker["ticker"]), flush=True)
                            newVolume = get_balances(config,ticker["ticker"])
                            if newVolume:
                                account.tickers[key]["volume"] = newVolume
                        elif result == "failed":
                            print("Failed to buy ${} of {}".format(str(buy_value),ticker["ticker"]))
                        else:
                            print("Place limit order to buy ${} of {}".format(str(buy_value),ticker["ticker"]))
                            account.tickers[key]["limitTrade"]["open"] = True
                            account.tickers[key]["limitTrade"]["id"] = result
                            account.tickers[key]["limitTrade"]["ts"] = account.serverTime

                else:
                    account.tickers[key]["difference"] = 0

        highTicker = {
            "ticker":"",
            "diff":0
        }
        for ticker in account.tickers:
            if ticker["difference"] > highTicker["diff"]:
                highTicker["diff"] = ticker["difference"]
                highTicker["ticker"] = ticker["ticker"]

        print(" "*150, end="\r", flush=True)
        print(f"{dt_object.hour}:{dt_object.minute}:{dt_object.second} ~ '{account.market.upper()}' trade, Equity: ${account.equity}; Highest Swing {highTicker["ticker"]}:{trunc(highTicker["diff"]*100,1)}% Balance Value: ${trunc(baseBalance,2)}", end="\r", flush=True)
    elif account.market == "suspended":
        pass
    else:
        print(" "*150, end="\r", flush=True)
        print(f"{dt_object.hour}:{dt_object.minute}:{dt_object.second} ~ '{account.market.upper()}' trade, Equity: ${account.equity}; Highest Swing {highTicker["ticker"]}:{trunc(highTicker["diff"]*100,1)}% Balance Value: ${trunc(baseBalance,2)}", end="\r", flush=True)


    
@bmd_logger
def bot_loop(account=Status, config=Config, server="closed"):
    config.update()
    account.margin = config.margin
    checkTime(account, config, server)
    if server != 'closed':
        bot(account,config)
    account.save_state()
    ts=int(time.time())
    checkIn(int(time.time()),account,config)


                    


session = create_session() #For Alpaca requests

if __name__=="__main__":
    account = Status()
    try:
        print("Loading account . . .")
        account.load_state()
    except Exception as e:
        account.save_state()
    config = Config()
    server = "closed" #Tracking Exchange open and closed
    schedule.every(1).minute.do(bot_loop, account=account, config=config, server=server)
    schedule.every(5).minute.do(checkBalances, account=account, config=config) #Confirm Balance Amounts
    schedule.every().day.at("22:00").do(day_end, account=account, config=config)
    while True:
        try:
            schedule.run_pending()
            time.sleep(5)
        except Exception as e:
            account.load_state()
            raise
