from dotenv import dotenv_values
import requests, json, time, datetime, traceback

config=dotenv_values(".env")
account = {}
status = "running"
url_base = ""
apiKey = ""
apiSecret = ""
if config["VERSION"] == "paper":
    url_base = "https://paper-api.alpaca."
    apiKey = config["PAPERKEY"]
    apiSecret = config["PAPERSECRET"]
elif config["VERSION"] == "real":
    url_base = "https://api.alpaca."
    apiKey = config["KEY"]
    apiSecret = config["SECRET"]

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def create_order(volume,direction,symbol, type="value"):
    url=url_base+"markets/v2/orders"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
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

    response = requests.post(url, json=payload, headers=headers)
    if str(response.status_code) == '200':
        json_response = response.json()
        status = "open"
        while status == "open":
            url = url_base+"markets/v2/orders/"+str(json_response["id"])
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": apiKey,
                "APCA-API-SECRET-KEY": apiSecret
            }
            response = requests.get(url, headers=headers)
            if str(response.status_code) == '200':
                json_response = response.json()
                if json_response["status"] == "filled" or json_response["status"] == "canceled" or json_response["status"] == "expired":
                    status = "closed"
                    print_str = direction+": "+symbol+"; Price: "+str(json_response["filled_avg_price"])
                    print(" "*100, end="\r", flush=True)
                    print(print_str)
                else:
                    time.sleep(1)
            else:
                status = "close"
                print(response.text)




def get_account():
    global account
    url = url_base+"markets/v2/account"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.get(url, headers=header)
    json_response = response.json()
    return json_response

def get_balances():
    url = url_base+"markets/v2/positions"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }

    response = requests.get(url, headers=headers)
    json_response = response.json()
    return json_response

def bot():
    global account
    dayStart = False
    print(config["VERSION"])
    while True:
        try:
            url = url_base+"markets/v2/clock"
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": apiKey,
                "APCA-API-SECRET-KEY": apiSecret
            }
            response = requests.get(url, headers=headers)
            json_response = response.json()
            if json_response["is_open"]:
                if not dayStart:
                    print(" "*150, end="\r", flush=True)
                    print(str(datetime.date.today()))
                    dayStart = True
                base = get_account()
                balances = get_balances()
                total = float(base["cash"])
                for entry in balances:
                    total += float(entry["market_value"])
                balance_value = total/(int(config["BOTNUMBER"])+0.5)
                with open("topEquities.json", "r") as file:
                    equity_list = json.loads(file.read())
                    for entry in balances:
                        found = False
                        for i in range(int(config["BOTNUMBER"])):
                            equity = equity_list[i]
                            if equity["symbol"] == entry["symbol"]:
                                found=True
                                break
                        if not found:
                            if float(entry["market_value"]) > 1:
                                print("Selling Equity not to be traded:"+str(equity["symbol"]))
                                sell_volume = float(entry["qty"])
                                create_order(sell_volume,"sell",entry["symbol"],"qty")

                    for i in range(int(config["BOTNUMBER"])):
                        equity = equity_list[i]
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
                    print_str += str(value)+":"+str(trunc(account[value]*100,1))+"% | "
                print(" "*150, end="\r", flush=True)
                currentTime = datetime.datetime.now()
                print(currentTime.strftime("%H:%M:%S")+" ~ "+print_str, end="\r", flush=True)
                time.sleep(1)
            else:
#                if dayStart:
#                    base = get_account()
#                    balances = get_balances()
#                    total = float(base["cash"])
#                    for entry in balances:
#                        total += float(entry["market_value"])
#                    requests(post day end total)
                dayStart = False
                tsFormat = "%Y-%m-%dT%H:%M:%S"
                sleepTime = (datetime.datetime.strptime(json_response["next_open"][:19],tsFormat) - datetime.datetime.strptime(json_response["timestamp"][:19],tsFormat)).seconds
                print(" "*150, end="\r", flush=True)
                print("Sleep timer: "+str(sleepTime/3600)[:4]+"hrs ~ "+str(json_response["next_open"])[:19], end="\r", flush=True)
                timeToSleep = sleepTime*.8
                if timeToSleep < 60:
                    timeToSleep = 60
                time.sleep(timeToSleep)
        except:
            traceback.print_exc()



if __name__=="__main__":
    bot()
