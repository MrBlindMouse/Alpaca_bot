from dotenv import dotenv_values
import requests, json, time, datetime

config=dotenv_values(".env")
account = {}
status = "running"

def create_order(volume,direction,symbol):
    url="https://paper-api.alpaca.markets/v2/orders"
    header = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config["PAPERKEY"],
        "APCA-API-SECRET-KEY": config["PAPERSECRET"]
    }
    payload = {
        "side":direction,
        "type":"market",
        "time_in_force":"day",
        "symbol":symbol,
        "qty": str(volume),
    }
    response = requests.post(url, json=payload, headers=header)
    json_response = response.json()
    print(json.dumps(json_response,indent=4))
    return json_response


def get_account():
    global account
    url = "https://paper-api.alpaca.markets/v2/account"
    header = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config["PAPERKEY"],
        "APCA-API-SECRET-KEY": config["PAPERSECRET"]
    }
    response = requests.get(url, headers=header)
    json_response = response.json()
    return json_response

def get_balances():
    url = "https://paper-api.alpaca.markets/v2/positions"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config["PAPERKEY"],
        "APCA-API-SECRET-KEY": config["PAPERSECRET"]
    }

    response = requests.get(url, headers=headers)
    json_response = response.json()
    return json_response

def bot():
    global account
    while True:
        url = "https://paper-api.alpaca.markets/v2/clock"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": config["PAPERKEY"],
            "APCA-API-SECRET-KEY": config["PAPERSECRET"]
        }
        response = requests.get(url, headers=headers)
        json_response = response.json()
        if json_response["is_open"]:
            base = get_account()
            balances = get_balances()
            total = float(base["cash"])
            for entry in balances:
                total += float(entry["market_value"])
            balance_value = total/11
            with open("topEquities.json", "r") as file:
                for equity in json.loads(file.read()):
                    found = False
                    for entry in balances:
                        if entry["symbol"] == equity["symbol"]:
                            symbol = entry["symbol"]
                            found = True
                            if float(entry["market_value"]) > balance_value:
                                diff = (float(entry["market_value"]) - balance_value)/balance_value
                                if symbol not in account:
                                    account[symbol] = diff
                                elif diff > account[symbol]:
                                    account[symbol] = diff
                                elif diff < (account[symbol]*(1-account[symbol])) and diff > float(config["MARGIN"]):
                                    sell_volume = float(entry["market_value"])*diff
                                    create_order(sell_volume,"sell",symbol)
                                    account[symbol] = 0
                                elif diff < float(config["MARGIN"]):
                                    account[symbol] = diff

                            else:
                                diff = (balance_value - float(entry["market_value"]))/balance_value
                                if symbol not in account:
                                    account[symbol] = diff
                                elif diff > account[symbol]:
                                    account[symbol] = diff
                                elif diff < (account[symbol]*(1-account[symbol])) and diff > float(config["MARGIN"]):
                                    buy_volume = float(entry["market_value"])*diff
                                    create_order(sell_volume,"buy",symbol)
                                    account[symbol] = 0
                                elif diff < float(config["MARGIN"]):
                                    account[symbol] = diff

                    if not found:
                        print(equity["symbol"]+" not found")
                        url = "https://data.alpaca.markets/v2/stocks/"+equity["symbol"]+"/snapshot?feed=iex"
                        headers = {
                            "accept": "application/json",
                            "APCA-API-KEY-ID": config["PAPERKEY"],
                            "APCA-API-SECRET-KEY": config["PAPERSECRET"]
                        }
                        json_response = requests.get(url, headers=headers).json()
                        price = float(json_response["minuteBar"]["c"])
                        volume = balance_value/price
                        create_order(volume,"buy",equity["symbol"])
            print("ALX:"+str(account["ALX"])[:5]+" | BLK:"+str(account["BLK"])[:5]+" | AVGO:"+str(account["AVGO"])[:5]+" | EQIX:"+str(account["EQIX"])[:5]+" | CABO:"+str(account["CABO"])[:5]+" | ESS:"+str(account["ESS"])[:5]+" | NEU:"+str(account["NEU"])[:5]+" | WSO:"+str(account["WSO"])[:5]+" | SPG:"+str(account["SPG"])[:5]+" | AMGN:"+str(account["AMGN"])[:5], end="\r", flush=True)
            time.sleep(60)
            #print("Running . . .", end="\r", flush=True)
        else:
            tsFormat = "%Y-%m-%dT%H:%M:%S"
            sleepTime = (datetime.datetime.strptime(json_response["next_open"][:-6],tsFormat) - datetime.datetime.strptime(json_response["timestamp"][:-16],tsFormat)).seconds
            print("Sleep time:"+str(sleepTime))
            break
            time.sleep(sleepTime)



if __name__=="__main__":
    bot()