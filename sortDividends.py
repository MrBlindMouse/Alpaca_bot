from datetime import datetime
import json, requests
from dotenv import dotenv_values
config=dotenv_values(".env")

dividends=[]
sortedDivs = []

def get_period(start):
    end =datetime.now()
    diff = end - start
    return (diff.days/365)

def main():
    global dividends
    with open("dividends.json", 'r') as file:
        dividends = json.loads(file.read())
    for equity in dividends:
        symbol = equity["symbol"]
        total=0
        number=0
        avg=0
        high=0
        low=1000
        start_date = datetime.now()
        for entry in equity["dividends"]:
            dateFormat='%Y-%m-%d'
            date = datetime.strptime(entry["date"],dateFormat)
            if date < start_date:
                start_date = date
            total+=entry["rate"]
            if entry["rate"] > high:
                high=entry["rate"]
            if entry["rate"] < low:
                low=entry["rate"]
            number+=1
        avg=total/number
        change_high = (high-avg)/avg
        change_low = (avg-low)/avg
        period = get_period(start_date)
        if equity["price"] != 1:
            if (period*3) <= number and period > 1:
                if change_high < 1 and change_low < 1:
                    sortedDivs.append({
                        "symbol":symbol,
                        "period":period,
                        "flux_high":change_high,
                        "flux_low":change_low,
                    })

    sortedDivs.sort(key=lambda x: x["annual"], reverse=True)

    with open("topEquities.json","w+") as file:
        json_write=[]
        for key in range(10):
            json_write.append(sortedDivs[key])
        file.write(json.dumps(json_write,indent=4))


if __name__ == "__main__":
    main()