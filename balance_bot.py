from dotenv import dotenv_values
import requests, json, time, datetime, traceback
import traceback, sys

status = {}

def bmd_logger(function):
    def exception_handler(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            print(" "*150, end="\r", flush=True)
            print(str(datetime.datetime.today())+" ~ Exception raised during "+function.__name__, flush=True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            message = traceback.extract_tb(exc_traceback)
            post_message = "Exception raised during "+function.__name__+'<br>'
            for line in message.format():
                post_message += line+'<br>'
            post_message += str(exc_type)+'\n<br>'+str(exc_value)
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
                print('Original exception: ')
                print(post_message)
            time.sleep(10)
    return exception_handler

def scheduler():
    global status
    accounts = []
    config = dotenv_values(".env")
    tsFormat = "%Y-%m-%dT%H:%M:%S"
    ts = int(datetime.datetime.now().timestamp())
    for i in len(config["DETAILS"]):
        entry = config["DETAILS"][i]



def trunc(value,digits):
    x = 10**digits
    return int(value*x)/x

if __name__ == "__main__":
    while True:
        scheduler()