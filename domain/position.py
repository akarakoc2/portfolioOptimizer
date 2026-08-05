from .transaction import Transaction


class Position():
    def __init__(self,first_transaction):
        if first_transaction.transaction_type != "BUY":
            raise ValueError("Please firtst buy a stock to start a position")
        self.ticker = first_transaction.ticker
        self.currency = first_transaction.currency
        self.opening_date = first_transaction.transaction_date
        
        self.transactions = []
        self.transactions.append(first_transaction)
        
    def add_transaction(self, transaction):
        if self.ticker != transaction.ticker:
            raise ValueError("The position you want to add is not opened yet!")

        if transaction.transaction_type == 'SELL':
            if transaction.quantity > self.net_quantity:
                raise ValueError("Not enough position to sell")
            
        self.transactions.append(transaction)

    @property
    def net_quantity(self):
        total_quantity = 0
        for i in self.transactions:
            if i.transaction_type == "BUY":
                total_quantity += i.quantity
            elif i.transaction_type == 'SELL':
                total_quantity -= i.quantity
        return total_quantity
    
    @property
    def average_cost_basis(self):

        total_buys = [x for x in self.transactions if x.transaction_type == "BUY"]
        cost_total = 0
        total_quantity = 0
        for i in total_buys:
            cost_total += i.quantity * i.cost_per_unit
            total_quantity += i.quantity

        if total_quantity != 0:
            average_cost = cost_total / total_quantity
        else:
            average_cost = 0

        return average_cost
    
    @property
    def is_open(self):
        return self.net_quantity > 0 


    def __repr__(self):
        return f"Position | {self.ticker} | {self.net_quantity} | {self.average_cost_basis} | Open: {self.is_open} | Open Since: {self.opening_date} "
       
