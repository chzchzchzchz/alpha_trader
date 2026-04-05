"""Skeptic Agent - Validates everything."""
class Skeptic:
    def check_data(self, signals):
        if not signals: return "REJECT: No data"
        return "PASS"
    def check_signal(self, sig):
        if sig.get("confidence",0) < 0.55: return "REJECT: Low confidence"
        return "PASS"
