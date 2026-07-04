from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio



if __name__ == "__main__":
    
    transcation_test = Transaction('AAPL', 20220603,'BUY', 3,5,1,'EUR')
    transaction2 = Transaction('aapl', 20220603,'BUY', 1,6,4,'EUR')
    pos1 = Position(transcation_test)
    pos1.add_transaction(transaction2)
    port1 = Portfolio("ATK_1", "EUR")
    port1.add_transaction(transaction=transcation_test)
    
    print(transaction2)
    print('\n')
    print(pos1)
