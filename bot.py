from dotenv import dotenv_values
import requests, json, time, datetime, traceback
import traceback, sys

config=dotenv_values(".env")
account = {}
status = {
    "trading":"close",
    "checkinTS":0,
    }
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

def bmd_logger(function):
    def exception_handler():
        result = None
        try:
            result = function()
        except:
            print(" "*150, end="\r", flush=True)
            print("Exception raised during "+function.__name__, flush=True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            message = traceback.extract_tb(exc_traceback)
            post_message = "Exception raised during "+function.__name__+'<br>'+'\n'
            for line in message.format():
                post_message += line+'<br>'
            payload = {
                "code": "2",
                "app": "Alpaca",
                "snippet": post_message
            }
            try:
                result = requests.post("https://www.bmd-studios.com/log", json=payload)
                if result.status_code != 200:
                    print("Logging Error")
                    print("Status code: "+str(result.status_code))
                    print(result.text)
                    print('Original exception: ')
                    print(post_message)
            except Exception as c:
                print("BMD logger server down . . .")
                print(str(c))
            time.sleep(10)
        return result
    return exception_handler

@bmd_logger
def create_order(volume,direction,symbol,currentPrice, marketStatus, type="value"):

    if marketStatus == "open":
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
            limitPrice = trunc(float(currentPrice)*1.005,2)
        elif direction == "sell":
            limitPrice = trunc(float(currentPrice)*.995,2)
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
    if marketStatus == "open":
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

@bmd_logger
def get_account():
    url = url_base+"markets/v2/account"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.get(url, headers=headers)
    json_response = response.json()
    return json_response

@bmd_logger
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

@bmd_logger
def delete_order(id):
    url = url_base+"markets/v2/orders/"+id

    headers = {
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    requests.delete(url, headers=headers)

def day_end():
    balances = get_balances()
    base = get_account()
    cash = float(base["cash"])
    cost = cash
    equity = cash
    investment = 0

    for entry in balances:
        equity += float(entry["market_value"])
        cost += float(entry["cost_basis"])

    url = url_base+"markets/v2/account/activities?activity_types=CSD,CSW&direction=desc&page_size=100"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.get(url, headers=headers)
    json_response = response.json()
    for entry in json_response:
        if entry["activity_type"] == "CSD":
            investment += float(entry["net_amount"])
        elif entry["activity_type"] == "CSW":
            investment -= float(entry["net_amount"])
    

    url = 'https://www.bmd-studios.com/record'
    header = {
        "accept": "application/json"
    }
    payload={
        "ts":str(int(datetime.datetime.now().timestamp())),
        "equity":trunc(equity,2),
        "cost":trunc(cost,2),
        "investment":trunc(investment,2)
    }
    requests.post(url=url,json=payload)

def checkin(ts,status):
    url = 'https://www.bmd-studios.com/bot'
    header = {
        "accept": "application/json"
    }
    payload={
        "id":"02",
        "bot_name":"Alpaca",
        "ts":str(ts),
        "status":status
    }
    requests.post(url=url,json=payload)

    #Sending general info to bmd
    url = 'https://www.bmd-studios.com/general'
    header = {
        "accept": "application/json"
    }
    payload={
        "id":"02",
        "ts":str(ts),
        "name":"Alpaca",
        "json_string":json.dumps(account)
    }
    requests.post(url=url,json=payload)

@bmd_logger
def bot():
    global account
    global status
    tsFormat = "%Y-%m-%dT%H:%M:%S"
    ts = int(datetime.datetime.now().timestamp())
    if int(status["checkinTS"]) == 0 :
        status["checkinTS"] = ts
    if (ts - status["checkinTS"]) > 60:
        checkin(ts,status["trading"])
        status["checkinTS"] = ts

    
    url = url_base+"markets/v2/clock"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": apiSecret
    }
    response = requests.get(url, headers=headers)
    server_time = response.json()
    current_server_time = datetime.datetime.strptime(server_time["timestamp"][:19],tsFormat)
    if server_time["is_open"]:
        margin = float(config["MARGIN"])
        if status["trading"] != "open":
            print(" "*150, end="\r", flush=True)
            print(str(datetime.date.today())+": Market Open", flush=True)
            status["trading"] = "open"
    elif current_server_time.weekday() >= 0 and current_server_time.weekday() <= 4 and current_server_time.hour > 4  and current_server_time.hour < 20:
        print(str(current_server_time.weekday()))
        if status["trading"] != "extended":
            print(" "*150, end="\r", flush=True)
            print(str(datetime.date.today())+":Market Close, trading extended hrs ~ Next open: "+str(server_time["next_open"])[:19], flush=True)
            status["trading"] = "extended"
            day_end()
        margin = float(config["MARGIN"]) *1.5
    else:
        if status["trading"] != "closed":
            print(" "*150, end="\r", flush=True)
            print(str(datetime.date.today())+":Market Close ~ Next open: "+str(server_time["next_open"])[:19], flush=True)
            status["trading"] = "closed"
            account_symbols = list(account.keys())
            account_values = list(account.values())
            if len(account_symbols) == (config["BOTNUMBER"]):
                for i in range(int(config["BOTNUMBER"])):
                    if issubclass(type(account_values[i]),str):
                        delete[account[account_symbols[i]]]
        time.sleep(120)

#                    base = get_account()
#                    balances = get_balances()
#                    total = float(base["cash"])
#                    for entry in balances:
#                        total += float(entry["market_value"])
#                    requests(post day end total)
#                    today = datetime.datetime.today()
#                    if int(today.month()) in [1,6] and int(today.day()) == 1:
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


    if status["trading"] != "closed":
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
                        create_order(sell_volume,"sell",entry["symbol"],entry["current_price"], status["trading"],"qty")

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
                            if status["trading"] == "open":
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
                                    result = create_order(sell_value,"sell",symbol,entry["current_price"], status["trading"])
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
                                    result = create_order(sell_value,"sell",symbol,entry["current_price"], status["trading"])
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
                                    result = create_order(buy_value,"buy",symbol,entry["current_price"], status["trading"])
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
                                    result = create_order(buy_value,"buy",symbol,entry["current_price"], status["trading"])
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
                    result = create_order(balance_value,"buy",equity["symbol"],entry["current_price"], status["trading"])
                    if result == 'done':
                        account[symbol] = 0
                    elif result == 'failed':
                        account[symbol] = diff
                        print(" "*150, end="\r", flush=True)
                        print(equity["symbol"]+" Market trade failed")
                    else:
                        account[symbol] = result

        print_str = "Margin: "+str(trunc(margin*100,2))+"% |"
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


if __name__=="__main__":
    while True:
        bot()
