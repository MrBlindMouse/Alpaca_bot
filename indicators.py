import requests, datetime, time


def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def beta(tickers,config):
    """Returns beta(volatility) values for supplied tickers, over 1 year period. Baseline is 1"""
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    bars = []
    today = datetime.date.today()
    oldDate = today - datetime.timedelta(days=365)
    for ticker in tickers:
        url = "https://data.alpaca.markets/v2/stocks/{}/bars?timeframe=1D&start={}&end={}&limit=1000&adjustment=split&feed=iex&sort=asc".format(ticker,oldDate,today)
        result = requests.get(url, headers=headers)

        # Alpaca API Rate limit
        time.sleep(0.4)

        if result.status_code == 200:
            jsonResult = result.json()
            closeList = []
            for bar in jsonResult["bars"]:
                closeList.append(bar["c"])
            bars.append({
                "ticker":ticker,
                "closeList":closeList
                })
    returns = []

    #Finding Daily and avg returns per ticker
    for ticker in bars:
        returnList = []
        for key,close in enumerate(ticker["closeList"]):
            if key != 0:
                dailyReturn = (ticker["closeList"][key-1]-ticker["closeList"][key])/ticker["closeList"][key-1]
                returnList.append(dailyReturn)
        avgRetruns = sum(returnList)/len(returnList)
        details = {
            "ticker":ticker["ticker"],
            "avgReturn":avgRetruns,
            "returns":returnList
        }
        returns.append(details)
    
    #Finding Daily and avg returns for index
    indexReturns = []
    days = len(returns[0]["returns"])
    for day in range(days):
        avgReturn = 0
        for ticker in returns:
            try:
                avgReturn += ticker["returns"][day]
            except Exception as e:
                pass
        avgReturn = avgReturn/len(returns)
        indexReturns.append(avgReturn)
    indexAvgReturn = sum(indexReturns)/len(indexReturns)

    #Finding variance for index
    variance = 0
    for day in range(days):
        variance += (indexReturns[day]-indexAvgReturn)**2
    variance = variance/days

    #Finding covariance and calculation beta per ticker
    beta = []
    for details in returns:
        covariance = 0
        for day in range(days):
            covariance += (details["returns"][day]-details["avgReturn"])*(indexReturns[day]-indexAvgReturn)
        covariance = covariance/days
        beta.append({
            "ticker":details["ticker"],
            "beta":trunc((covariance/variance),2)
        })
    return beta
    
def trend(tickers,config):
    """
    Returns RSI value and SMA trend for supplied tickers
    rsi: 70~50 is trending up, 50~25 is trending down, >70 is over bought, <30 is oversold
    trend: Short SMA / Long SMA, 1 for a neutral trend, for >1< reflects trend
    """
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    
    bars = []
    today = datetime.date.today()
    oldDate = today - datetime.timedelta(days=90)
    for ticker in tickers:
        url = "https://data.alpaca.markets/v2/stocks/{}/bars?timeframe=1D&start={}&end={}&limit=1000&adjustment=split&feed=iex&sort=asc".format(ticker,oldDate,today)
        result = requests.get(url, headers=headers)

        # Alpaca API Rate limit
        time.sleep(0.4)

        if result.status_code == 200:
            jsonResult = result.json()
            closeList = []
            for bar in jsonResult["bars"]:
                closeList.append(bar["c"])
            bars.append({
                "ticker":ticker,
                "closeList":closeList
                })
    details = []
    for ticker in bars:
        rsiList = ticker["closeList"][-14:]

        #RSI calcs
        positiveChange = 0
        negativeChange = 0
        for key,item in enumerate(rsiList):
            if key != 0:
                change = rsiList[key] - rsiList[key-1]
                if change > 0:
                    positiveChange += change
                else:
                    negativeChange += abs(change)
        positiveChange = positiveChange/14
        negativeChange = negativeChange/14
        rsi = 100-(100/(1+(positiveChange/negativeChange)))

        #SMA trend calcs
        shortSMAList = ticker["closeList"][-14:]
        shortSMA = sum(shortSMAList)/len(shortSMAList)
        longSMA = sum(ticker["closeList"])/len(ticker["closeList"])
        smaTrend = (shortSMA/longSMA)
        details.append({
            "ticker":ticker["ticker"],
            "rsi":trunc(rsi,2),
            "trend":trunc(smaTrend,2)
        })
    return details