import pandas as pd

class TWRcalculator():
    def __init__(self, portfolio_value, positions):
        self.portfolio_value = portfolio_value
        self.cashflows = {}
        
        # Check if positions is a dictionary (e.g., {'AAPL': Position(...)}) or a list
        pos_list = positions.values() if isinstance(positions, dict) else positions
        
        # Loop through all Position objects
        for pos in pos_list:
            # Loop through all Transaction objects inside the Position
            for tx in pos.transactions:
                date = pd.Timestamp(tx.transaction_date)
                
                # Calculate the cash amount based on the logic in your average_cost_basis method.
                # (Note: If your Transaction object has a .fees attribute, you should add it here)
                tx_value = tx.quantity * tx.cost_per_unit 
                
                if tx.transaction_type == 'BUY':
                    # A BUY means cash is deposited into the portfolio assets
                    self.cashflows[date] = self.cashflows.get(date, 0) + tx_value
                elif tx.transaction_type == 'SELL':
                    # A SELL means cash is withdrawn from the portfolio assets
                    self.cashflows[date] = self.cashflows.get(date, 0) - tx_value
                    
        self.cashflow_dates = list(self.cashflows.keys())
        
        self.inception_date = portfolio_value.index.min()
        self.end_date = portfolio_value.index.max()

    def _get_subperiod_boundries(self):
        boundaries = self.cashflow_dates.copy()
        boundaries.insert(0, self.inception_date)
        boundaries.append(self.end_date)
        
        # Remove duplicates and sort chronologically
        boundaries = list(set(boundaries))
        boundaries = sorted(boundaries)
        return boundaries
    
    def _calculate_subperiod_returns(self, start_date, end_date):
        start_value = self.portfolio_value.asof(start_date)
        end_value = self.portfolio_value.asof(end_date)

        if start_value == 0 or pd.isna(start_value):
            return 0
        
        # Look up the aggregated cash flows for this specific end date
        cf_amount = self.cashflows.get(pd.Timestamp(end_date), 0)
        
        # Subtract the cash inflow to isolate pure market growth
        organic_end_value = end_value - cf_amount
        
        return (organic_end_value / start_value) - 1

    def calculate_twr(self):
        sub_returns = list()
        self.sub_periods = self._get_subperiod_boundries()
        
        for i in range(len(self.sub_periods) - 1):
            start_date = self.sub_periods[i]
            end_date = self.sub_periods[i+1]
            
            return_s = self._calculate_subperiod_returns(start_date, end_date)
            sub_returns.append(return_s)

        twr = 1.0
        for r in sub_returns:
            twr *= (1 + r)
            
        return twr - 1