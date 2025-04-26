from dotenv import dotenv_values
import requests, json, time, datetime, math
import traceback, sys, os
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests_ratelimiter import LimiterSession
import pickle
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
        self.balanceTS = 0
        self.betaTS = 0

    def check_balances(self, positions, config):
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
            if (currentTS - self.betaTS) > 604800: #7 Days
                print("Updateting Beta")
                betaList = indicators.beta(tickers, config, session)
                self.betaTS = currentTS
                for key, value in enumerate(new_list):
                    for entry in betaList:
                        if new_list[key]["ticker"] == entry["ticker"]:
                            new_list[key]["beta"] = entry["beta"]
            
            self.tickers = new_list
            self.save_state()
        #else:
            #Send Report to BMD

    def save_state(self):
        with open(self.STATE_FILE, 'wb') as file:
            pickle.dump({
                'tickers':self.tickers,
                'equity':self.equity,
                'market':self.market,
                'serverTime':self.serverTime,
                'margin':self.margin,
                'balanceTS':self.balanceTS,
                'betaTS':self.betaTS
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
                self.balanceTS = state['balanceTS']
                self.betaTS = state['betaTS']
        else:
            print("State file not found")
            raise

class Config():
    def update(self):
        config = dotenv_values(".env")
        self.urlBase = "https://paper-api.alpaca." if config["VERSION"] == "PAPER" else "https://api.alpaca."
        self.apiKey = config["API_KEY"]
        self.apiSecret = config["API_SECRET"]
        self.poligonKey = config["POLIGON_KEY"]
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
    url = "https://www.slickcharts.com/nasdaq100"
    result = requests.get(url,headers={'User-Agent': 'Mozilla/5.0'})
    tickers = None
    if str(result.status_code) == '200':
        parsedResult = BeautifulSoup(result.content, 'html.parser')
        tableBody = parsedResult.find('tbody', id="companyListComponent")
        tableRows = tableBody.find_all('tr')
        for line in tableRows:
            tableCell = line.find_all('td')
            i=0
            for cell in tableCell:
                if i == 2:
                    if not tickers:
                        tickers = []
                    tickers.append(cell.text)
                i += 1
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
            payload = {
                "code": "2",
                "app": "Alpaca",
                "snippet": post_message
            }
            try:
                result = requests.post("https://www.bmd-studios.com/log", json=payload)
                if result.status_code != 200:
                    print("Logging Error")
                    print("Status code: "+str(result.status_code))
                    print(result.text)
                    print('Original exception: ')
                    print(post_message)
            except Exception as c:
                print("BMD logger server down . . .")
                print(str(c))
                print('Original exception: ')
                print(post_message)
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
    url = "{}markets/v2/account".format(config.urlBase)
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    response = session.get(url, headers=headers)
    json_response = response.json()
    return json_response

def get_balances(config):
    url = "{}markets/v2/positions".format(config.urlBase)
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }

    response = session.get(url, headers=headers)
    json_response = response.json()
    return json_response

def get_balance(config, symbol):
    url = "{}markets/v2/positions/{}".format(config.urlBase,symbol)
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }

    response = session.get(url, headers=headers)
    if str(response.status_code) == "200":
        json_response = response.json()
        return float(json_response["qty"])
    else:
        print(" "*150, end="\r", flush=True)
        print("Error finding {} balance".format(symbol), flush=True)
        print(response.reason)
        print(response.text)
        return None

"""
def day_end(account,config):
    balances = get_balances()
    base = get_account()
    cash = float(base["cash"])
    cost = cash
    equity = cash
    investment = 0

    for entry in balances:
        equity += float(entry["market_value"])
        cost += float(entry["cost_basis"])

    url = config.urlBase+"markets/v2/account/activities?activity_types=CSD,CSW&direction=desc&page_size=100"
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

"""

def checkIn(ts, account):
    """
    Basic Check In to BMD
    """
    url = 'https://www.bmd-studios.com/bot'
    headers = {
        "accept": "application/json"
    }
    payload={
        "id":"03",
        "bot_name":"Alpaca Test",
        "ts":str(ts),
        "status":account.market
    }
    requests.post(url=url,json=payload)


@bmd_logger
def bot(account,config):
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
        ordersURL = "{}markets/v2/orders".format(config.urlBase) # Finding un-recorded open limit orders
        result = session.get(ordersURL, headers=headers)
        if str(result.status_code) == "200":
            jsonResult = result.json()
            for item in jsonResult:
                for key,ticker in enumerate(account.tickers):
                    if item["symbol"] == ticker["ticker"]:
                        if not ticker["limitTrade"]["open"]:
                            account.tickers[key]['limitTrade']["open"] = True
                            account.tickers[key]['limitTrade']["id"] = item["id"]
                            account.tickers[key]['limitTrade']["ts"] = 0
                        break


    url = "{}markets/v2/clock".format(config.urlBase)
    result = session.get(url, headers=headers)
    if str(result.status_code) == "200":
        jsonResult = result.json()
        time_string = jsonResult["timestamp"]
        time_string = time_string[:19]+time_string[-6:]
        dt_object = datetime.datetime.strptime(time_string,"%Y-%m-%dT%H:%M:%S%z")
        account.serverTime = int(dt_object.timestamp())

        if (account.serverTime - account.balanceTS) > 3600:
            positions = get_balances(config)
            account.check_balances(positions, config)
            account.balanceTS = account.serverTime

        if jsonResult["is_open"]:
            if account.market == "extended":
                print(" "*150, end="\r", flush=True)
                print("Trade start for {}-{}-{}".format(str(dt_object.year),str(dt_object.month),str(dt_object.day)), flush=True)
                print("Updateting Equity List . . .")
                account.check_ticker(config)
            account.market = "open"
        elif int(dt_object.hour) >= 4 and int(dt_object.hour) < 20:
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
                        checkIn(int(time.time()), account)
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
            if account.market == "closed":
                print(" "*150, end="\r", flush=True)
                print("{}:{}:{} ~ Market Closed, Equity: ${}".format(dt_object.hour,dt_object.minute,dt_object.second, str(account.equity)), end="\r", flush=True)
                time.sleep(180)
            else:
                print(" "*150, end="\r", flush=True)
                print("Market Closed for {}-{}-{}".format(str(dt_object.year),str(dt_object.month),str(dt_object.day)), flush=True)
                account.market = "closed"


        if account.market != "closed" and account.market != "holiday":
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
            if str(result.status_code) == "200":
                jsonResult = result.json()
                for key,ticker in enumerate(account.tickers):
                    #if float(jsonResult[ticker["ticker"]]["latestQuote"]["bp"]) != 0 and float(jsonResult[ticker["ticker"]]["latestQuote"]["ap"]) != 0:
                    #    account.tickers[key]["price"] = (float(jsonResult[ticker["ticker"]]["latestQuote"]["bp"])+float(jsonResult[ticker["ticker"]]["latestQuote"]["ap"]))/2
                    #else:
                    account.tickers[key]["price"] = float(jsonResult[ticker["ticker"]]["minuteBar"]["vw"])

            else:
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
                weight = 1+(2*(generalTrend-1))
                weight = max(0.5, min(1, weight)) #Adjustment capped at 50% during downwards trend
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
                            newVolume = get_balance(config,ticker["ticker"])
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
                        newVolume = get_balance(config,ticker["ticker"])
                        if newVolume and newVolume != ticker["volume"]:
                            account.tickers[key]["volume"] = newVolume

                if ticker["volume"] == 0 and not ticker["limitTrade"]["open"]:   #Buy initial shares
                    result = create_order(config,balance_value,"buy",ticker["ticker"],account.market,ticker["price"],"value")
                    print(" "*150, end="\r", flush=True)
                    print("Buyinf initial {} shares".format(ticker["ticker"]), flush=True)
                    if result == "success":
                        print("Bought ${} of {}".format(balance_value,ticker["ticker"]), )
                        newVolume = get_balance(config,ticker["ticker"])
                        if newVolume and newVolume != ticker["volume"]:
                            account.tickers[key]["volume"] = newVolume
                    elif result == "failed":
                        print("Failed to buy ${} of {}".format(balance_value,ticker["ticker"]), )
                    else:
                        print("Place limit order to buy ${} of {}".format(balance_value,ticker["ticker"]), )
                        account.tickers[key]["limitTrade"]["open"] = True
                        account.tickers[key]["limitTrade"]["id"] = result
                        account.tickers[key]["limitTrade"]["ts"] = account.serverTime

                beta= ticker["beta"]
                marginFactor = 1+(math.log(max(0.1, abs(beta)))/math.log(2))     #logarithmic scaling, [-2,2]
                margin = config.margin *(1+(0.2 * marginFactor)) if config.dynamicMargin else config.margin #Factor affects 20% of margin
                margin = min(config.margin*1.3, max(config.margin*.7, margin))  #Adjustment caps at 30%

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
                                newVolume = get_balance(config,ticker["ticker"])
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
                                newVolume = get_balance(config,ticker["ticker"])
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
            print("{}:{}:{} ~ '{}' trade, Equity: ${}; Highest Swing {}:{}% Balance Value: ${}".format(dt_object.hour,dt_object.minute,dt_object.second,account.market.upper(),account.equity,highTicker["ticker"],trunc(highTicker["diff"]*100,1),trunc(baseBalance,2)), end="\r", flush=True)
            time.sleep(5)
    else:
        print(" "*150, end="\r", flush=True)
        print("Error finding Server Time", flush=True)
        print(result.reason)
        print(result.text)
    




                    


session = create_session() #For Alpaca requests

if __name__=="__main__":
    account = Status()
    try:
        print("Loading account . . .")
        account.load_state()
    except Exception as e:
        account.save_state()
    config = Config()
    checkInTS = 0
    while True:
        try:
            config.update()
            account.margin = config.margin
            bot(account,config)
            account.save_state()
            ts = int(time.time())
            if ts - checkInTS > 60:
                checkIn(ts, account)
                checkInTS = ts
        except Exception as e:
            account.load_state()
            raise
