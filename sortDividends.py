from datetime import datetime
import json

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
        if (get_period(start_date)*3) <= number:
            sortedDivs.append({
                "symbol":symbol,
                "total":total,
                "average":avg,
                "flux_high":change_high,
                "flux_low":change_low,
                "number":number
            })

    sortedDivs.sort(key=lambda x: x["total"], reverse=True)
    with open("topEquities.json","w+") as file:
        json_write=[]
        for key in range(10):
            json_write.append(sortedDivs[key])
        file.write(json.dumps(json_write,indent=4))


if __name__ == "__main__":
    main()