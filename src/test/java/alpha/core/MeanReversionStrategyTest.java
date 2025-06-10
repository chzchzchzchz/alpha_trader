package alpha.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for MeanReversionStrategy
 */
class ArrayMockDataHandler implements DataHandler {
    private final double[] closes;

    ArrayMockDataHandler(double[] closes) {
        this.closes = closes;
    }

    @Override
    public Double getLatestPrice(String symbol) {
        return closes.length > 0 ? closes[closes.length - 1] : null;
    }

    @Override
    public Double getPreviousClose(String symbol) {
        return closes.length > 1 ? closes[closes.length - 2] : null;
    }

    @Override
    public double[] getRecentCloses(String symbol, int limit) {
        return closes;
    }

    @Override
    public double[] getRecentHighs(String symbol, int limit) {
        return new double[0];
    }
}

public class MeanReversionStrategyTest {

    @Test
    void detectsBuySignalBelowMean() {
        // Price is 2% below mean
        double[] prices = {100, 100, 100, 100, 98};  // mean=100, last=98
        DataHandler dataHandler = new ArrayMockDataHandler(prices);
        String[] symbols = {"AAPL"};

        var strategy = new alpha.strategy.MeanReversionStrategy(dataHandler, symbols);
        var signal = strategy.generateSignal();

        assertNotNull(signal);
        assertEquals("AAPL", signal.symbol);
        assertEquals("buy", signal.side);
        assertTrue(signal.shouldTrade);
        assertEquals(98.0, signal.currentPrice);
    }

    @Test
    void detectsSellSignalAboveMean() {
        // Price is 2% above mean
        double[] prices = {100, 100, 100, 100, 102};  // mean=100, last=102
        DataHandler dataHandler = new ArrayMockDataHandler(prices);
        String[] symbols = {"AAPL"};

        var strategy = new alpha.strategy.MeanReversionStrategy(dataHandler, symbols);
        var signal = strategy.generateSignal();

        assertNotNull(signal);
        assertEquals("AAPL", signal.symbol);
        assertEquals("sell", signal.side);
        assertTrue(signal.shouldTrade);
        assertEquals(102.0, signal.currentPrice);
    }

    @Test
    void noSignalWithinThreshold() {
        // Price within 1% of mean
        double[] prices = {100, 100, 100, 100, 100.5};
        DataHandler dataHandler = new ArrayMockDataHandler(prices);
        String[] symbols = {"AAPL"};

        var strategy = new alpha.strategy.MeanReversionStrategy(dataHandler, symbols);
        var signal = strategy.generateSignal();

        assertNull(signal);
    }

    @Test
    void handlesEmptyData() {
        // No data scenario
        double[] prices = {};
        DataHandler dataHandler = new ArrayMockDataHandler(prices);
        String[] symbols = {"AAPL"};

        var strategy = new alpha.strategy.MeanReversionStrategy(dataHandler, symbols);
        var signal = strategy.generateSignal();

        assertNull(signal);
    }

    @Test
    void handlesSingleSymbolNoSignal() {
        // Tests iterating through symbols with no signal
        double[] prices = {100};  // Not enough data for mean
        DataHandler dataHandler = new ArrayMockDataHandler(prices);
        String[] symbols = {"AAPL", "GOOGL", "MSFT"};  // Multiple symbols

        var strategy = new alpha.strategy.MeanReversionStrategy(dataHandler, symbols);
        var signal = strategy.generateSignal();

        assertNull(signal);
    }
}
