package alpha.strategy;

import alpha.core.BaseStrategy;
import alpha.core.SignalResult;
import alpha.core.DataHandler;

/**
 * MomentumBreakoutStrategy implements a simple high breakout logic.
 * <p>
 * Pass: Generates buy if last close equals the 20-bar high.
 * Fail: Returns null if no trade should occur.
 * </p>
 */
public class MomentumBreakoutStrategy implements BaseStrategy {
    private final String[] symbols;
    private final DataHandler dataHandler;

    public MomentumBreakoutStrategy(DataHandler dataHandler, String[] symbols) {
        this.dataHandler = dataHandler;
        this.symbols = symbols;
    }

    @Override
    public String[] getSymbols() {
        return symbols;
    }

    @Override
    public SignalResult generateSignal() {
        for (String symbol : symbols) {
            double[] highs = dataHandler.getRecentHighs(symbol, 20);
            double[] closes = dataHandler.getRecentCloses(symbol, 20);
            if (highs == null || closes == null || closes.length == 0) continue;
            double high = java.util.Arrays.stream(highs).max().orElse(0);
            double last = closes[closes.length - 1];
            if (last >= high) {
                return new SignalResult(symbol, "buy", true, last);
            }
        }
        return null;
    }
}
