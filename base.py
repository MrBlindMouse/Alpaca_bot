import os
from dotenv import load_dotenv, dotenv_values
import requests
import json
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass

load_dotenv()
key = os.getenv("KEY")
secret = os.getenv("SECRET")


def main():
    client = TradingClient(key, secret, paper=True)
    params = GetAssetsRequest(asset_class=AssetClass.STOCK)
    assets = client.get_all_assets(params)


if __name__ == "__main__":
    main()