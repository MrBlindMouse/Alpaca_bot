# Alpaca_bot
Personal saving and investment bot balancing high-dividend stocks and ETFs on the Alpaca API.

**Run:** `python bot.py`

## Setup
.env file required. Format following:
'''
PAPERKEY='Paper api key'
PAPERSECRET=Paper api secret'
KEY='Live api key'
SECRET='Live api secret'
MARGIN=Bot margin, float. Reccommended 0.02~0.15
VERSION="paper"/"real"
BOTNUMBER=Number of active equities, int
'''