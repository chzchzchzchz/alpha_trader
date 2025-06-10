package alpha.strategy;

import alpha.core.BaseStrategy;
import alpha.core.SignalResult;
import alpha.core.DataHandler;

/**
 * OpeningRangeBreakoutStrategy implements a 15-min high breakout logic.
 * <p>
 * Pass: Generates buy if last close exceeds 15-min high.
 * Fail: Returns null if no trade should occur.
 * </p>
 */
public class OpeningRangeBreakoutStrategy implements BaseStrategy {
    private final String[] symbols;
    private final int rangeMinutes;
    private final DataHandler dataHandler;

    public OpeningRangeBreakoutStrategy(DataHandler dataHandler, String[] symbols, int rangeMinutes) {
        this.dataHandler = dataHandler;
        this.symbols = symbols;
        this.rangeMinutes = rangeMinutes;
    }

    @Override
    public String[] getSymbols() {
        return symbols;
    }

    @Override
    public SignalResult generateSignal() {
        for (String symbol : symbols) {
            double[] highs = dataHandler.getRecentHighs(symbol, rangeMinutes);
            double[] closes = dataHandler.getRecentCloses(symbol, rangeMinutes);
            if (highs == null || closes == null || closes.length < rangeMinutes) continue;
            double rngHigh = java.util.Arrays.stream(highs, 0, highs.length - 1).max().orElse(0);
            double lastClose = closes[closes.length - 1];
            if (lastClose > rngHigh) {
                return new SignalResult(symbol, "buy", true, lastClose);
            }
        }
        return null;
    }
}
