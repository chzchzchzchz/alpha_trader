import pandas as pd
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from core.logger import get_logger

class DataHandler:
    """
    Uses alpaca-py to fetch historical and live minute bars.
    """

    def __init__(self, cfg):
        self.logger = get_logger()
        alp = cfg.alpaca
        self.client = StockHistoricalDataClient(
            api_key=alp.key,
            secret_key=alp.secret
        )
        self.history_days = cfg.data.history_days

    def get_bars(self,
                 symbol: str,
                 timeframe: str = "1Min",
                 limit: int = 1000) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.history_days)

        tf_map = {
            "1Min":  TimeFrame.Minute,
            "5Min":  TimeFrame.FiveMin,
            "15Min": TimeFrame.FifteenMin,
            "1Day":  TimeFrame.Day
        }
        tf = tf_map.get(timeframe, TimeFrame.Minute)

        req = StockBarsRequest(
            symbol_or_symbols=[symbol],
            start=start,
            end=end,
            timeframe=tf,
            limit=limit
        )

        bars = self.client.get_stock_bars(request_params=req)
        df = bars.df
        if df.empty:
            self.logger.warning(f"No bars returned for {symbol}")
            return df

        df = df.xs(symbol, level="symbol").copy()
        df.rename(columns={
            "open_":   "open",
            "high_":   "high",
            "low_":    "low",
            "close_":  "close",
            "volume_": "volume"
        }, inplace=True)
        return df

    def get_latest_price(self, symbol: str) -> float:
        df = self.get_bars(symbol, limit=1)
        return float(df["close"].iloc[-1]) if not df.empty else None

    def get_previous_close(self, symbol: str) -> float:
        df = self.get_bars(symbol, timeframe="1Day", limit=2)
        return float(df["close"].iloc[-2]) if len(df) >= 2 else None
