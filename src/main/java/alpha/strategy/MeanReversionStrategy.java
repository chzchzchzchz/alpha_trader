package alpha.strategy;

import alpha.core.BaseStrategy;
import alpha.core.SignalResult;
import alpha.core.DataHandler;
import java.util.Arrays;

/**
 * MeanReversionStrategy implements a simple mean reversion logic.
 * <p>
 * Pass: Generates buy if price is 1% below mean, sell if 1% above.
 * Fail: Returns null if no trade should occur.
 * </p>
 */
public class MeanReversionStrategy implements BaseStrategy {
    private final String[] symbols;
    private final DataHandler dataHandler;

    public MeanReversionStrategy(DataHandler dataHandler, String[] symbols) {
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
            double[] closes = dataHandler.getRecentCloses(symbol, 30);
            if (closes == null || closes.length == 0) continue;
            double mean = Arrays.stream(closes).average().orElse(0);
            double last = closes[closes.length - 1];
            double dev = (last - mean) / mean;
            if (dev < -0.01) {
                return new SignalResult(symbol, "buy", true, last);
            } else if (dev > 0.01) {
                return new SignalResult(symbol, "sell", true, last);
            }
        }
        return null;
    }
}
