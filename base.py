import os
from dotenv import load_dotenv, dotenv_values
import requests
import json
from alpaca.data.historical import StockHistoricalDataClient

load_dotenv()
key = os.getenv("KEY")
secret = os.getenv("SECRET")


def main():
    url = "https://data.alpaca.markets/v1beta1/corporate-actions?types=cash_dividend%2C%20stock_dividend&start=2020-01-01&limit=100&sort=desc"
    headers = {"accept":"application/json"}
    response = requests.get(url, headers=headers)
    print(json.dumps(response, indent=4))


if __name__ == "__main__":
    main()