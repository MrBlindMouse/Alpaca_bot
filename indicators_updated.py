import requests
import datetime

def trunc(value, digits):
    x = 10**digits
    return int(value * x) / x

def beta(tickers, config, session):
    """Returns beta(volatility) values for supplied tickers, over 1 year period. Baseline is 1"""
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    today = datetime.date.today()
    old_date = today - datetime.timedelta(days=365)
    symbols_str = ','.join(tickers)
    url = f"https://data.alpaca.markets/v2/stocks/bars?symbols={symbols_str}&timeframe=1D&start={old_date}&end={today}&limit=1000&adjustment=split&feed=iex&sort=asc"
    result = session.get(url, headers=headers)
    bars = []
    if result.status_code == 200:
        json_result = result.json()
        for ticker in tickers:
            if ticker in json_result.get('bars', {}):
                close_list = [bar['c'] for bar in json_result['bars'][ticker]]
                bars.append({"ticker": ticker, "closeList": close_list})
    returns = []
    for ticker in bars:
        close_list = ticker['closeList']
        return_list = [(close_list[key] - close_list[key-1]) / close_list[key-1] for key in range(1, len(close_list))]
        avg_return = sum(return_list) / len(return_list) if return_list else 0
        returns.append({"ticker": ticker['ticker'], "avgReturn": avg_return, "returns": return_list})
    if not returns:
        return [{"ticker": t, "beta": 1} for t in tickers]
    days = max(len(r['returns']) for r in returns)
    index_returns = []
    for day in range(days):
        day_returns = [r['returns'][day] for r in returns if day < len(r['returns'])]
        avg_return = sum(day_returns) / len(day_returns) if day_returns else 0
        index_returns.append(avg_return)
    index_avg_return = sum(index_returns) / len(index_returns) if index_returns else 0
    variance = sum((ir - index_avg_return)**2 for ir in index_returns) / len(index_returns) if index_returns else 0
    beta_list = []
    for details in returns:
        if variance == 0 or not details['returns']:
            beta_list.append({"ticker": details['ticker'], "beta": 1})
            continue
        min_days = min(days, len(details['returns']))
        covariance = sum((details['returns'][day] - details['avgReturn']) * (index_returns[day] - index_avg_return) for day in range(min_days)) / min_days
        beta_list.append({"ticker": details['ticker'], "beta": trunc(covariance / variance, 2)})
    return beta_list

def trend(tickers, config, session):
    """
    Returns RSI value and SMA trend for supplied tickers
    rsi: 70~50 is trending up, 50~25 is trending down, >70 is over bought, <30 is oversold
    trend: Short SMA / Long SMA, 1 for a neutral trend, >1 or <1 reflects trend
    """
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret
    }
    today = datetime.date.today()
    old_date = today - datetime.timedelta(days=90)
    symbols_str = ','.join(tickers)
    url = f"https://data.alpaca.markets/v2/stocks/bars?symbols={symbols_str}&timeframe=1D&start={old_date}&end={today}&limit=1000&adjustment=split&feed=iex&sort=asc"
    result = session.get(url, headers=headers)
    bars = []
    if result.status_code == 200:
        json_result = result.json()
        for ticker in tickers:
            if ticker in json_result.get('bars', {}):
                close_list = [bar['c'] for bar in json_result['bars'][ticker]]
                bars.append({"ticker": ticker, "closeList": close_list})
    details = []
    for ticker in bars:
        close_list = ticker['closeList']
        if len(close_list) < 14:
            details.append({"ticker": ticker['ticker'], "rsi": 50, "trend": 1})
            continue
        rsi_list = close_list[-14:]
        positive_change = sum(max(rsi_list[key] - rsi_list[key-1], 0) for key in range(1, len(rsi_list))) / 14
        negative_change = sum(max(rsi_list[key-1] - rsi_list[key], 0) for key in range(1, len(rsi_list))) / 14
        if negative_change == 0:
            rsi = 100 if positive_change > 0 else 0
        else:
            rsi = 100 - (100 / (1 + (positive_change / negative_change)))
        short_sma = sum(close_list[-14:]) / 14
        long_sma = sum(close_list) / len(close_list)
        sma_trend = short_sma / long_sma if long_sma != 0 else 1
        details.append({"ticker": ticker['ticker'], "rsi": trunc(rsi, 2), "trend": trunc(sma_trend, 2)})
    return details