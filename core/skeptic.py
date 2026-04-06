class SkepticAgent:
    def check_data(self, signals):
        if not signals:
            return "REJECT: No data"
        return "PASS"
    def check_signal(self, signal):
        conf = signal.get("confidence", 0.5)
        if conf < 0.50:
            return "REJECT: Very weak confidence"
        if conf < 0.55:
            return "CAUTION: Low confidence"
        return "PASS"
