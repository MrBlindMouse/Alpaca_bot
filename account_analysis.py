import os, pickle, json, math, time, datetime
from dotenv import dotenv_values
import requests

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

"""
Reads the pkl state file, and performs analysis on trends/rsi/beta values. Adjust as required.
"""

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def sorted(tickers):

    return tickers["difference"]

def readPickle():
    """Read account state file"""
    state = None
    if os.path.exists("trading_state.pkl"):
        with open("trading_state.pkl", 'rb') as file:
            state = pickle.load(file)
    else:
        print("State file not found")
    return state

def savePickle(state):
    """Save account state file"""
    with open("trading_state.pkl", 'wb') as file:
        pickle.dump(state, file)

def checkEquity():
    config = Config()
    config.update()
    
    url = "https://paper-api.alpaca.markets/v2/account"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    result = requests.get(url, headers=headers)
    result.raise_for_status()
    result = result.json()
    cash = float(result["cash"])
    equity = float(result["equity"])

    url = "https://paper-api.alpaca.markets/v2/positions"
    result = requests.get(url, headers=headers)
    result.raise_for_status()
    result = result.json()

    cost = 0
    for entry in result:
        cost += float(entry["cost_basis"])
    cost += cash

    print(f"Total equity:${equity} on cost:${cost}")

def checkTrends(tickers=[]):
    account = readPickle()
    print(f"Beta ts:{datetime.datetime.fromtimestamp(account["betaTS"])}")
    stockList = account["tickers"]
    stockList.sort(key=sorted)
    marketTrend = 0
    marketRSI = 0
    for line in reversed(stockList):
        marketTrend += float(line["trend"])
        marketRSI += float(line["rsi"])
        if tickers and line["ticker"] in tickers:
            print(f"{line["ticker"]}\tswing:{trunc(line["difference"]*100,2)}\tbeta:{trunc(line["beta"],2)},\ttrend:{trunc(line["trend"],2)},\trsi:{trunc(line["rsi"],2)}")
        else:
            print(f"{line["ticker"]}\tswing:{trunc(line["difference"]*100,2)}\tbeta:{trunc(line["beta"],2)},\ttrend:{trunc(line["trend"],2)},\trsi:{trunc(line["rsi"],2)}")
    marketTrend = marketTrend/len(stockList)
    marketRSI = marketRSI/len(stockList)
    generalTrend = (marketTrend+(marketRSI/50))/2
    weight = max(0.5,min(1,(1+(2*(generalTrend-1)))))
    print(f"Market Trend:{marketTrend:.2f} Market RSI:{marketRSI:.2f}")
    print(f"General Trend:{(generalTrend*100):.1f} ~ trend weight:{weight}")


if __name__ == "__main__":
    #checkEquity()
    
    checkTrends()
