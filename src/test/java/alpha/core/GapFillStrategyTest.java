package alpha.core;

import org.junit.jupiter.api.Test;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for GapFillStrategy
 */
class MockDataHandler implements DataHandler {
    private final Double latestPrice;
    private final Double previousClose;

    MockDataHandler(Double latestPrice, Double previousClose) {
        this.latestPrice = latestPrice;
        this.previousClose = previousClose;
    }

    @Override
    public Double getLatestPrice(String symbol) {
        return latestPrice;
    }

    @Override
    public Double getPreviousClose(String symbol) {
        return previousClose;
    }

    @Override
    public double[] getRecentCloses(String symbol, int limit) {
        return new double[0];
    }

    @Override
    public double[] getRecentHighs(String symbol, int limit) {
        return new double[0];
    }
}

public class GapFillStrategyTest {

    @Test
    void detectsBuyGapDown() {
        // Gap down of 1% (buy signal)
        DataHandler dataHandler = new MockDataHandler(99.0, 100.0);
        String[] symbols = {"AAPL"};
        double threshold = 0.005; // 0.5%

        var strategy = new alpha.strategy.GapFillStrategy(dataHandler, symbols, threshold);
        var signal = strategy.generateSignal();

        assertNotNull(signal);
        assertEquals("AAPL", signal.symbol);
        assertEquals("buy", signal.side);
        assertTrue(signal.shouldTrade);
        assertEquals(99.0, signal.currentPrice);
    }

    @Test
    void detectsSellGapUp() {
        // Gap up of 1% (sell signal)
        DataHandler dataHandler = new MockDataHandler(101.0, 100.0);
        String[] symbols = {"AAPL"};
        double threshold = 0.005; // 0.5%

        var strategy = new alpha.strategy.GapFillStrategy(dataHandler, symbols, threshold);
        var signal = strategy.generateSignal();

        assertNotNull(signal);
        assertEquals("AAPL", signal.symbol);
        assertEquals("sell", signal.side);
        assertTrue(signal.shouldTrade);
        assertEquals(101.0, signal.currentPrice);
    }

    @Test
    void noSignalOnSmallGap() {
        // Gap of 0.3% (below threshold)
        DataHandler dataHandler = new MockDataHandler(100.3, 100.0);
        String[] symbols = {"AAPL"};
        double threshold = 0.005; // 0.5%

        var strategy = new alpha.strategy.GapFillStrategy(dataHandler, symbols, threshold);
        var signal = strategy.generateSignal();

        assertNull(signal);
    }

    @Test
    void handlesNullPrices() {
        // Missing data scenario
        DataHandler dataHandler = new MockDataHandler(null, 100.0);
        String[] symbols = {"AAPL"};
        double threshold = 0.005;

        var strategy = new alpha.strategy.GapFillStrategy(dataHandler, symbols, threshold);
        var signal = strategy.generateSignal();

        assertNull(signal);
    }
}
