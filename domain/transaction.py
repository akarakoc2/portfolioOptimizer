from datetime import date


class Transaction:
    VALID_TYPES = {"BUY", "SELL"}
    VALID_CURRENCIES = {"EUR", "USD", "GBP"}
    
    def __init__(self,ticker, transaction_date, transaction_type, quantity, cost_per_unit, fees, currency):

        currency = currency.upper()

        if currency not in self.VALID_CURRENCIES:
            print('You are trying to use invalid currency please change the currency type')
            raise ValueError()    


        self.ticker = ticker
        self.transaction_date = transaction_date
        self.transaction_type = transaction_type
        self.quantity = quantity
        self.cost_per_unit = cost_per_unit
        self.fees = fees
        self. currency = currency

        

transaction = Transaction('aapl', 2000, 'BUY', 3, 4, 0, 'EUR')