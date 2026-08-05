from datetime import date


class Transaction:
    VALID_TYPES = {"BUY", "SELL"}
    VALID_CURRENCIES = {"EUR", "USD", "GBP"}
    
    def __init__(self,ticker, transaction_date, transaction_type, quantity, cost_per_unit, fees, currency):
        ticker = ticker.upper()
        currency = currency.upper()
        transaction_type = transaction_type.upper()

        if currency not in self.VALID_CURRENCIES:
            raise ValueError(f'You are trying to use invalid currency please change the currency type')

        if transaction_type not in self.VALID_TYPES:
            raise ValueError(f"Please indicate a {self.VALID_TYPES} type transaction")

        if quantity <= 0:
            raise ValueError("Please enter quantity positive")
        
        if fees < 0:
            raise ValueError("Please enter fees positive")

        if ticker.strip() == "":
            raise ValueError("Please Enter Valid Ticker")
        
        self.ticker = ticker
        self.transaction_date = transaction_date
        self.transaction_type = transaction_type
        self.quantity = quantity
        self.cost_per_unit = cost_per_unit
        self.fees = fees
        self.currency = currency


        if self.transaction_type == "BUY":
            self.total_cost = (self.cost_per_unit  * self.quantity) + self.fees
        elif self.transaction_type == "SELL":
            self.total_cost = (self.cost_per_unit * self.quantity) - self.fees 

    @property
    def cash_flow(self):
        return -self.total_cost if self.transaction_type == "BUY" else self.total_cost
        


    def __repr__(self):
        return f"Transaction | {self.ticker} | {self.transaction_type} | Price: {self.cost_per_unit} | Total: {self.total_cost} | {self.currency} | {self.transaction_date}"

