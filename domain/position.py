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

        # Deliberately no date-ordering check here: transactions arrive in
        # whatever order the caller has them, and a CSV import will not be
        # sorted. Selling before you own is caught in
        # PortfolioTimeSeries.build_holding_frames, where the dates are known.
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
    
    # Fractional share counts do not cancel exactly: a bought-then-fully-sold
    # position lands on a float residue near 1e-16 rather than on zero.
    QUANTITY_TOLERANCE = 1e-9

    @property
    def average_cost_basis(self):
        """Moving average cost of the shares currently held.

        Walks in date order, carrying a running total: a BUY adds its cost, a
        SELL removes shares at the average prevailing then, which leaves the
        average untouched for whatever remains. Once the position closes the
        running total returns to zero, so reopening it starts a fresh basis.

        Averaging every BUY ever made instead -- which is what this did -- let a
        lot closed years ago drag the basis of a position reopened since.
        """
        ordered = sorted(self.transactions, key=lambda t: str(t.transaction_date))

        held = 0.0
        cost = 0.0

        for transaction in ordered:
            if transaction.transaction_type == "BUY":
                held += transaction.quantity
                cost += transaction.quantity * transaction.cost_per_unit
            else:
                average = cost / held if held > self.QUANTITY_TOLERANCE else 0.0
                held -= transaction.quantity
                cost -= transaction.quantity * average

            if held <= self.QUANTITY_TOLERANCE:
                held = 0.0
                cost = 0.0

        if held <= self.QUANTITY_TOLERANCE:
            return 0.0

        return cost / held

    @property
    def is_open(self):
        return self.net_quantity > self.QUANTITY_TOLERANCE


    def __repr__(self):
        return f"Position | {self.ticker} | {self.net_quantity} | {self.average_cost_basis} | Open: {self.is_open} | Open Since: {self.opening_date} "
       
