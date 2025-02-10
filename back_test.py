import csv, json, time

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def start():
    stocks = ['mstr','tsla','amd']
    stockData = []
    for item in stocks:
        fileName = item+'.csv'
        priceData = []
        with open(fileName, mode='r') as file:
            data = csv.reader(file)
            for line in data:
                if line[0] != 'Date':
                    if line[1][:1]=='$':
                        priceData.append((line[0],float(line[3][1:])))
                        priceData.append((line[0],float(line[1][1:])))
                    else:
                        priceData.append((line[0],float(line[3])))
                        priceData.append((line[0],float(line[1])))
        stockData.append({
            'ticker':item,
            'data':priceData,
            'diff':0,
            'buyVolume':0,
            'buyValue':0,
            'sellVolume':0,
            'sellValue':0,
        })

    currentLedger = {
            'cash':10000,
        }
    for stock in stocks:
        currentLedger[stock]=0

    margin = 0.04
    balanceRate = len(stocks)+(len(stocks)*2*margin)

    dateRange = 0
    for stock in stockData:
        if dateRange == 0:
            dateRange = len(stock['data'])
        elif len(stock['data']) < dateRange:
            dateRange = len(stock['data'])

    tradeLedger=[]

    for i in reversed(range(dateRange)):
        totalValue=float(currentLedger['cash'])
        for stock in stockData:
            totalValue += float(currentLedger[stock['ticker']])*float(stock['data'][i][1])
        balanceValue = totalValue/balanceRate

        for key,stock in enumerate(stockData):
            stockValue = currentLedger[stock['ticker']]*stock['data'][i][1]
            if stockValue > balanceValue:
                diff = (stockValue-balanceValue)/balanceValue
                if diff > 4*margin:
                    sellValue = stockValue-balanceValue
                    sellVolume = sellValue/stock['data'][i][1]
                    currentLedger['cash'] += sellValue
                    currentLedger[stock['ticker']] -= sellVolume
                    stockData[key]['diff'] = 0
                    stockData[key]['sellVolume'] += sellVolume
                    stockData[key]['sellValue'] += sellValue
                    tradeRecord = {
                        'date':stock['data'][i][0],
                        'ticker': stock['ticker'],
                        'cash': sellValue,
                        'stock': -sellVolume
                    }
                    print(" "*150, end="\r", flush=True)
                    print(stock['data'][i][0]+' Sell '+stock['ticker'].upper()+' Margin: '+str(trunc(diff*100,1)), end="\r", flush=True)
                    tradeLedger.append(tradeRecord)
                elif diff > stock['diff']:
                    stockData[key]['diff'] = diff
                elif diff < (stock['diff']*(1-stock['diff'])) and diff > margin:
                    sellValue = stockValue-balanceValue
                    sellVolume = sellValue/stock['data'][i][1]
                    currentLedger['cash'] += sellValue
                    currentLedger[stock['ticker']] -= sellVolume
                    stockData[key]['diff'] = 0
                    stockData[key]['sellVolume'] += sellVolume
                    stockData[key]['sellValue'] += sellValue
                    tradeRecord = {
                        'date':stock['data'][i][0],
                        'ticker': stock['ticker'],
                        'cash': sellValue,
                        'stock': -sellVolume
                    }
                    print(" "*150, end="\r", flush=True)
                    print(stock['data'][i][0]+' Sell '+stock['ticker'].upper()+' Margin: '+str(trunc(diff*100,1)), end="\r", flush=True)
                    tradeLedger.append(tradeRecord)
                elif diff < margin:
                    stockData[key]['diff'] = diff
            elif stockValue < balanceValue:
                diff = (balanceValue-stockValue)/balanceValue
                if diff > 4*margin:
                    buyValue = balanceValue-stockValue
                    buyVolume = buyValue/stock['data'][i][1]
                    currentLedger['cash'] -= buyValue
                    currentLedger[stock['ticker']] += buyVolume
                    stockData[key]['diff'] = 0
                    stockData[key]['buyVolume'] += buyVolume
                    stockData[key]['buyValue'] += buyValue
                    tradeRecord = {
                        'date':stock['data'][i][0],
                        'ticker': stock['ticker'],
                        'cash': -buyValue,
                        'stock': buyVolume
                    }
                    print(" "*150, end="\r", flush=True)
                    print(stock['data'][i][0]+' Buy '+stock['ticker'].upper()+' Margin: '+str(trunc(diff*100,1)), end="\r", flush=True)
                    tradeLedger.append(tradeRecord)
                elif diff > stock['diff']:
                    stockData[key]['diff'] = diff
                elif diff < (stock['diff']*(1-stock['diff'])) and diff > margin:
                    buyValue = balanceValue-stockValue
                    buyVolume = buyValue/stock['data'][i][1]
                    currentLedger['cash'] -= buyValue
                    currentLedger[stock['ticker']] += buyVolume
                    stockData[key]['diff'] = 0
                    stockData[key]['buyVolume'] += buyVolume
                    stockData[key]['buyValue'] += buyValue
                    tradeRecord = {
                        'date':stock['data'][i][0],
                        'ticker': stock['ticker'],
                        'cash': -buyValue,
                        'stock': buyVolume
                    }
                    print(" "*150, end="\r", flush=True)
                    print(stock['data'][i][0]+' Buy '+stock['ticker'].upper()+' Margin: '+str(trunc(diff*100,1)), end="\r", flush=True)
                    tradeLedger.append(tradeRecord)
                elif diff < margin:
                    stockData[key]['diff'] = diff

    with open('result.yaml', mode='w') as file:
        file.write(json.dumps(tradeLedger, indent=4))

    print(" "*150, end="\r", flush=True)
    print("Final Ledger:")
    print(json.dumps(currentLedger, indent=4))
    finalProfit = 0
    for stock in stockData:
        finalProfit += trunc(((stock['sellValue']/stock['sellVolume'])-(stock['buyValue']/stock['buyVolume']))*((stock['buyVolume']+stock['sellVolume'])/2),2)
#        print(json.dumps(printStock, indent=4))
    print("Final Est Trading Profit: "+str(trunc(finalProfit,2)))
    finalValue = currentLedger['cash']
    for stock in stockData:
        stockValue = float(currentLedger[stock["ticker"]])*float(stock['data'][0][1])
        print("Final "+str(stock['ticker']).upper()+" value: "+str(trunc(stockValue,2)))
        finalValue += stockValue
    print("Final value: "+str(trunc(finalValue,2)))

    print('*****************************************')
    print('Non bot est:')
    initValue = 10000/len(stocks)
    print('Initial buy value: '+str(trunc(initValue,2)))
    finalValue = 0
    for stock in stockData:
        initStock = initValue/float(stock['data'][-1][1])
        print(str(stock['ticker']).upper()+' initial buy: '+str(trunc(initStock,2)))
        finalStockValue = initStock*float(stock['data'][0][1])
        print('     Final value: '+str(trunc(finalStockValue,2)))
        finalValue += finalStockValue
    print('Final non bot value: '+str(trunc(finalValue,2)))






if __name__ == "__main__":
    start()