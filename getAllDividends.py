import requests
import json
from dotenv import dotenv_values


config=dotenv_values(".env")

key = config["PAPERKEY"]
secret = config["PAPERSECRET"]


def main():
    asstes_url = "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity"

    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret
    }

    equity_list = []
    response = requests.get(asstes_url, headers=headers)
    json_response = response.json()
    for line in json_response:
        if line["tradable"]==True and line["fractionable"]==True and line["class"]!="crypto":
            equity_list.append(line["symbol"])
    print("Number of Equities: "+str(len(equity_list)))
    div_list=[]
    for entry in equity_list:
        print("Symbol: "+entry)
        dividend_url = "https://data.alpaca.markets/v1beta1/corporate-actions?symbols="+entry+"&types=cash_dividend&start=2020-01-01&limit=1000&sort=desc"
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

            url = "https://data.alpaca.markets/v2/stocks/"+symbol+"/snapshot?feed=iex"
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
    main()