package alpha.strategy;

import alpha.core.BaseStrategy;
import alpha.core.SignalResult;
import alpha.core.DataHandler;

/**
 * GapFillStrategy implements a simple gap fill trading logic.
 * <p>
 * Pass: Generates a buy or sell signal if the open gap exceeds threshold.
 * Fail: Returns null if no trade should occur.
 * </p>
 */
public class GapFillStrategy implements BaseStrategy {
    private final String[] symbols;
    private final double threshold;
    private final DataHandler dataHandler;

    public GapFillStrategy(DataHandler dataHandler, String[] symbols, double threshold) {
        this.dataHandler = dataHandler;
        this.symbols = symbols;
        this.threshold = threshold;
    }

    @Override
    public String[] getSymbols() {
        return symbols;
    }

    @Override
    public SignalResult generateSignal() {
        for (String symbol : symbols) {
            Double cur = dataHandler.getLatestPrice(symbol);
            Double prev = dataHandler.getPreviousClose(symbol);
            if (cur == null || prev == null) continue;
            double gap = (cur - prev) / prev;
            if (Math.abs(gap) >= threshold) {
                String side = gap > 0 ? "sell" : "buy";
                return new SignalResult(symbol, side, true, cur);
            }
        }
        return null;
    }
}
