class KellySizer:
    def __init__(self, fraction=0.25):
        self.fraction = fraction
    def sizing(self, sig_prob=0.5, yes_price=50, no_price=50):
        if yes_price<=0 or no_price<=0: return 0.0
        implied = yes_price/100.0
        edge = (sig_prob-implied)/max(implied,0.01)
        return max(0, min(0.5, edge*self.fraction)) if edge>0 else 0.0
