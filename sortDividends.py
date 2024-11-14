from datetime import datetime
import json


def truncate(a,b):
    x = int(a*10**b)
    return x/10**b

def sort():

    dividends=[]
    sortedDivs = []
    topNumber = 50

    with open("dividends.json", 'r') as file:
        dividends = json.loads(file.read())
    print("Sorting "+str(len(dividends))+" equities . . .")
    for equity in dividends:
        symbol = equity["symbol"]
        total=0
        number=0
        avg=0
        high=0
        low=1000
        dateFormat='%Y-%m-%d'
        today = datetime.today()
        end_date = today
        start_date = datetime.strptime(equity["dividends"][-1]["date"],dateFormat)
        period = end_date-start_date
        if start_date != end_date:
            payoutNumber = len(equity["dividends"])/(period.days/365)
            wma = 0
            for entry in reversed(equity["dividends"]):
                if wma == 0:
                    wma = entry["rate"]
                else:
                    wma = ((wma*payoutNumber)+entry["rate"])/(payoutNumber+1)
                total+=entry["rate"]
                if entry["rate"] > high:
                    high=entry["rate"]
                if entry["rate"] < low:
                    low=entry["rate"]
                number+=1
                
            if payoutNumber > 3 and number >= 6 and truncate(period.days/365,1) >= 0.5:
                avgPayout=total/number
                wma_perc = wma/equity["price"]
                change_high = (high-avgPayout)/avgPayout
                change_low = (avgPayout-low)/avgPayout
                wyy = (wma_perc*number)/(period.days/365)
                if change_high < 1 and change_low < 1:
                    sortedDivs.append({
                        "symbol":symbol,
                        "annual%":truncate(wyy*100,2),
                        "payouts":payoutNumber,
                        "rate%":truncate((wma_perc)*100,2),
                        "period":str(truncate(period.days/365,1))+" years",
                        "flux_high":truncate(change_high*100,2),
                        "flux_low":truncate(change_low*100,2),
                    })

    sortedDivs.sort(key=lambda x: x["annual%"], reverse=True)

    with open("topEquities.json","w+") as file:
        json_write=[]
        for key in range(topNumber):
            json_write.append(sortedDivs[key])
        file.write(json.dumps(json_write,indent=4))


if __name__ == "__main__":
    sort()