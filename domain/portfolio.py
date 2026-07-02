from position import Position
from datetime import date
from transaction import Transaction

class Portfolio():
    def __init__(self, portfolio_name, portfolio_currency, creation_date = None):
        self.positions = {}
        self.portfolio_name = portfolio_name
        self.portfolio_currency = portfolio_currency
        if creation_date is None:
            self.creation_date = date.today()
        else:
            self.creation_date = creation_date
        
    def add_transaction(self, transaction):
        if transaction.ticker not in self.positions:
            self.positions[transaction.ticker] = Position(transaction)
        else:

            self.positions[transaction.ticker].add_transaction(transaction)
    def get_position(self, ticker):
        



    


    