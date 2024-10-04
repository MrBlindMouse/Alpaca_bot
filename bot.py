from dotenv import dotenv_values
import requests, json, time, datetime, traceback

config=dotenv_values(".env")
account = {}
status = "running"

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def create_order(volume,direction,symbol, type="value"):
    url="https://paper-api.alpaca.markets/v2/orders"
    header = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": config["PAPERKEY"],
        "APCA-API-SECRET-KEY": config["PAPERSECRET"]
    }
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
    print(" "*100, end="\r", flush=True)
    print(str(payload))

    response = requests.post(url, json=payload, headers=header)
    json_response = response.json()
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
        try:
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
                    equity_list = json.loads(file.read())
                    for entry in balances:
                        found = False
                        for equity in equity_list:
                            if equity["symbol"] == entry["symbol"]:
                                found=True
                                break
                        if not found:
                            print("Equity not to be trade:"+str(equity["symbol"]))
                            sell_volume = entry["qty"]
                            create_order(sell_volume,"sell",entry["symbol"],"qty")

                    for equity in equity_list:
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
                                        sell_value = float(entry["market_value"])*diff
                                        create_order(sell_value,"sell",symbol)
                                        account[symbol] = 0
                                    elif diff < float(config["MARGIN"]):
                                        account[symbol] = diff
                                    elif diff > 0.3:
                                        sell_value = float(entry["market_value"])*diff
                                        create_order(sell_value,"sell",symbol)
                                        account[symbol] = 0

                                else:
                                    diff = (balance_value - float(entry["market_value"]))/balance_value
                                    if symbol not in account:
                                        account[symbol] = diff
                                    elif diff > account[symbol]:
                                        account[symbol] = diff
                                    elif diff < (account[symbol]*(1-account[symbol])) and diff > float(config["MARGIN"]):
                                        buy_value = float(entry["market_value"])*diff
                                        create_order(buy_value,"buy",symbol)
                                        account[symbol] = 0
                                    elif diff < float(config["MARGIN"]):
                                        account[symbol] = diff
                                    elif diff > 0.3:
                                        sell_value = float(entry["market_value"])*diff
                                        create_order(sell_value,"sell",symbol)
                                        account[symbol] = 0
                                break

                        if not found:
                            print(equity["symbol"]+" not found")
                            create_order(balance_value,"buy",equity["symbol"])
                print_str = ""
                for key,value in enumerate(account):
                    print_str += str(value)+":"+str(trunc(account[value]*100),1)+"% | "
                print(" "*150, end="\r", flush=True)
                print(print_str, end="\r", flush=True)
                time.sleep(10)
                print(" "*150, end="\r", flush=True)
                print("Running . . .", end="\r", flush=True)
            else:
                tsFormat = "%Y-%m-%dT%H:%M:%S"
                sleepTime = (datetime.datetime.strptime(json_response["next_open"][:19],tsFormat) - datetime.datetime.strptime(json_response["timestamp"][:19],tsFormat)).seconds/3600
                print(" "*150, end="\r", flush=True)
                print("Sleep time:"+str(sleepTime)[:4]+"hrs ~ "+str(json_response["next_open"])[:19], end="\r", flush=True)
                time.sleep(300)
        except:
            traceback.print_exc()



if __name__=="__main__":
    bot()