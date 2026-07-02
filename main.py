import yfinance as yf

data = yf.Ticker("6324.T")
print(data.info)
