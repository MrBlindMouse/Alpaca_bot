from dotenv import dotenv_values
import requests, json, time, datetime, traceback

config=dotenv_values(".env")
account = {}
status = "running"
url_base = ""
apiKey = ""
apiSecret = ""
backSwing = 1
if config["VERSION"] == "paper":
    print("Trading Paper Monies . . .")
    url_base = "https://paper-api.alpaca."
    apiKey = config["PAPERKEY"]
    apiSecret = config["PAPERSECRET"]
elif config["VERSION"] == "real":
    print("Trading live . . .")
    url_base = "https://api.alpaca."
    apiKey = config["KEY"]
    apiSecret = config["SECRET"]

def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

def create_order(volume,direction,symbol,currentPrice, marketOpen, type="value"):

    if marketOpen:
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
            limitPrice = trunc(float(currentPrice)*1.003,2)
        elif direction == "sell":
            limitPrice = trunc(float(currentPrice)*.997,2)
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

    url=url_base+"markets/v2/orders"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.post(url, json=payload, headers=headers)
    if marketOpen:
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
                        print(" "*150, end="\r", flush=True)
                        print(print_str)
                    else:
                        time.sleep(1)
                else:
                    status = "close"
                    print(" "*150, end="\r", flush=True)
                    print(response.text)
            return "done"
        else:
            return "failed"
    else:
        if str(response.status_code) == '200':
            json_response = response.json()
            return str(json_response["id"])
        else:
            print(" "*150, end="\r", flush=True)
            return str(response.text)
            return "failed"




def get_account():
    global account
    url = url_base+"markets/v2/account"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.get(url, headers=headers)
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

def delete_order(id):
    url = url_base+"markets/v2/orders/"+id

    headers = {
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    requests.delete(url, headers=headers)

def bot():
    global account
    dayStart = False
    tsFormat = "%Y-%m-%dT%H:%M:%S"
    margin = 0
    while True:
        try:
            url = url_base+"markets/v2/clock"
            headers = {
                "accept": "application/json",
                "APCA-API-KEY-ID": apiKey,
                "APCA-API-SECRET-KEY": apiSecret
            }
            response = requests.get(url, headers=headers)
            server_time = response.json()
            marketOpen = server_time["is_open"]
            if marketOpen:
                margin = float(config["MARGIN"])
                if not dayStart:
                    print(" "*150, end="\r", flush=True)
                    print(str(datetime.date.today())+": Market Open", flush=True)
                    dayStart = True
            else:
                margin = float(config["MARGIN"]) + 0.01
                if dayStart:
                    print(" "*150, end="\r", flush=True)
                    print(str(datetime.date.today())+":Market Close, trading extended hrs ~ Next open: "+str(server_time["next_open"])[:19], flush=True)
                    dayStart = False
#                    base = get_account()
#                    balances = get_balances()
#                    total = float(base["cash"])
#                    for entry in balances:
#                        total += float(entry["market_value"])
#                    requests(post day end total)
#                    today = datetime.datetime.today()
#                    if int(today.month()) in [1,6] and int(today.day()) in [1,2,3,4,5,6]:
#                        url = url_base+"markets/v2/calendar?start="+str(today.year)+"-"+str(today.month)+"-1%2000%3A00%3A00&end="+str(today.year)+"-"+str(today.month)+"-01-06%2000%3A00%3A00"
#                        headers = {
#                            "accept": "application/json",
#                            "APCA-API-KEY-ID": apiKey,
#                            "APCA-API-SECRET-KEY": apiSecret
#                        }
#                        response = requests.get(url, headers=headers)
#                        json_response = response.json()
#                        update_date = datetime.datetime.strptime(json_response[0]["date"][:19],tsFormat)
#                        if update_date[:10] == today[:10]:
#                            update dividends
#                            sort dividends


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
                            print(" "*150, end="\r", flush=True)
                            print("Selling Equity not to be traded:"+str(entry["symbol"]))
                            sell_volume = float(entry["qty"])
                            create_order(sell_volume,"sell",entry["symbol"],entry["current_price"], marketOpen,"qty")

                for i in range(int(config["BOTNUMBER"])):
                    equity = equity_list[i]
                    found = False
                    for entry in balances:
                        if entry["symbol"] == equity["symbol"]:
                            symbol = entry["symbol"]
                            found = True
                            if symbol not in account:
                                    account[symbol] = 0

                            if issubclass(type(account[symbol]),str):
                                if marketOpen:
                                    delete_order(account[symbol])
                                print("Checking limit order . . .", end="\r", flush=True)
                                #Check limit order
                                url = url_base+"markets/v2/orders/"+account[symbol]
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
                                        account[symbol] = 0
                                        print_str = symbol+"; Price: "+str(json_response["filled_avg_price"])
                                        print(" "*150, end="\r", flush=True)
                                        print(print_str)
                                    else:
                                        delta = datetime.datetime.strptime(server_time["timestamp"][:19],tsFormat)-datetime.datetime.strptime(json_response["created_at"][:19],tsFormat)+datetime.timedelta(hours=4)
                                        if int(delta.seconds) > 600:
                                            print(" "*150, end="\r", flush=True)
                                            print("Old limit order, cancelling . . ."+account[symbol])
                                            delete_order(account[symbol])

                            else:
                                if float(entry["market_value"]) > balance_value:
                                    diff = (float(entry["market_value"]) - balance_value)/balance_value
                                    
                                    if diff > account[symbol]:
                                        account[symbol] = diff
                                    elif diff < (account[symbol]*(1-account[symbol])) and diff > margin:
                                        sell_value = balance_value*diff
                                        result = create_order(sell_value,"sell",symbol,entry["current_price"], marketOpen)
                                        if result == 'done':
                                            account[symbol] = 0
                                        elif result == 'failed':
                                            account[symbol] = diff
                                            print(" "*150, end="\r", flush=True)
                                            print(equity["symbol"]+" Market trade failed")
                                        else:
                                            account[symbol] = result
                                    elif diff < margin:
                                        account[symbol] = diff
                                    elif diff > margin*4:
                                        sell_value = balance_value*diff
                                        result = create_order(sell_value,"sell",symbol,entry["current_price"], marketOpen)
                                        if result == 'done':
                                            account[symbol] = 0
                                        elif result == 'failed':
                                            account[symbol] = diff
                                            print(" "*150, end="\r", flush=True)
                                            print(equity["symbol"]+" Market trade failed")
                                        else:
                                            account[symbol] = result
                                        #Implement Emergency Notification

                                elif float(entry["market_value"]) < balance_value:
                                    diff = (balance_value - float(entry["market_value"]))/balance_value
                                    
                                    if diff > account[symbol]:
                                        account[symbol] = diff
                                    elif diff < (account[symbol]*(1-account[symbol])) and diff > margin:
                                        buy_value = balance_value*diff
                                        result = create_order(buy_value,"buy",symbol,entry["current_price"], marketOpen)
                                        if result == 'done':
                                            account[symbol] = 0
                                        elif result == 'failed':
                                            account[symbol] = diff
                                            print(" "*150, end="\r", flush=True)
                                            print(equity["symbol"]+" Market trade failed")
                                        else:
                                            account[symbol] = result
                                    elif diff < margin:
                                        account[symbol] = diff
                                    elif diff > margin*4:
                                        buy_value = balance_value*diff
                                        result = create_order(buy_value,"buy",symbol,entry["current_price"], marketOpen)
                                        if result == 'done':
                                            account[symbol] = 0
                                        elif result == 'failed':
                                            account[symbol] = diff
                                            print(" "*150, end="\r", flush=True)
                                            print(equity["symbol"]+" Market trade failed")
                                        else:
                                            account[symbol] = result
                                        #Implement Emergency Notification
                            break

                    if not found:
                        print(" "*150, end="\r", flush=True)
                        print(equity["symbol"]+" not found, buying . . .")
                        result = create_order(balance_value,"buy",equity["symbol"],entry["current_price"], marketOpen)
                        if result == 'done':
                            account[symbol] = 0
                        elif result == 'failed':
                            account[symbol] = diff
                            print(" "*150, end="\r", flush=True)
                            print(equity["symbol"]+" Market trade failed")
                        else:
                            account[symbol] = result

            print_str = ""
            account_symbols = list(account.keys())
            account_values = list(account.values())
            for i in range(int(config["BOTNUMBER"])):
                if issubclass(type(account_values[i]),str):
                    print_str += str(account_symbols[i])+":limit | "
                else:
                    print_str += str(account_symbols[i])+":"+str(trunc(account_values[i]*100,1))+"% | "
            print(" "*150, end="\r", flush=True)
            currentTime = datetime.datetime.now()
            print(currentTime.strftime("%H:%M:%S")+" ~ "+print_str, end="\r", flush=True)
            time.sleep(1)


        except:
            traceback.print_exc()



if __name__=="__main__":
    bot()
