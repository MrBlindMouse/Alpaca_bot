import requests
import json, datetime
from dotenv import dotenv_values

def start():
    config=dotenv_values(".env")

    if config["VERSION"] == "paper":
        url_base = "https://paper-api.alpaca."
        key = config["PAPERKEY"]
        secret = config["PAPERSECRET"]
    elif config["VERSION"] == "real":
        url_base = "https://api.alpaca."
        key = config["KEY"]
        secret = config["SECRET"]


    today = datetime.date.today()
    searchPeriod = str(int(today.year)-4)

    assets_url = url_base+"markets/v2/assets?status=active&asset_class=us_equity"

    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret
    }

    equity_list = []
    response = requests.get(assets_url, headers=headers)
    json_response = response.json()
    for line in json_response:
        if line["tradable"]==True and line["fractionable"]==True and line["class"]!="crypto":
            equity_list.append(line["symbol"])
    print("Number of Equities: "+str(len(equity_list)))
    print("Period: "+searchPeriod+"-01-01 ~ "+str(today)[:10])
    div_list=[]
    for entry in equity_list:
        print("Symbol: "+entry)
        dividend_url = url_base+"markets/v1beta1/corporate-actions?symbols="+entry+"&types=cash_dividend&start="+searchPeriod+"-01-01&end="+str(today)[:10]+"&limit=1000&sort=desc"
        response = requests.get(dividend_url, headers=headers)
        json_response = response.json()
        payouts = []
        avg_rate=0
        total_payouts=0
        if "cash_dividends" in json_response["corporate_actions"]:
            for line in json_response["corporate_actions"]["cash_dividends"]:
                avg_rate+= line["rate"]
                total_payouts+=1
                payouts.append({
                    "date":line["ex_date"],
                    "rate":line["rate"]
                })

            url = url_base+"markets/v2/stocks/"+entry+"/snapshot?feed=iex"
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": "PKQ525I1RV9SFX54A1RX",
                "APCA-API-SECRET-KEY": "R4SAntnvlUBq6YuNEpkAy1cuX9d3hAjT2cfcUXEE"
            }
            response = requests.get(url, headers=headers)
            json_response = response.json()
            if "dailyBar" in json_response:
                price = float(json_response["dailyBar"]["c"])
                avg_rate=avg_rate/total_payouts
                print("Average dividend payout: "+str(avg_rate))
                print("Average dividend yield: "+str(avg_rate/price))
                div_list.append({
                    "symbol":entry,
                    "price":price,
                    "dividends":payouts
                })
    
    with open('dividends.json','w+') as file:
        file.write(json.dumps(div_list, indent=4))


if __name__ == "__main__":
    start()