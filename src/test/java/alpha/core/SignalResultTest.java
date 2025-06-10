package alpha.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for SignalResult
 */
public class SignalResultTest {

    @Test
    void createValidSignalResult() {
        SignalResult result = new SignalResult("AAPL", "buy", true, 150.50);
        assertEquals("AAPL", result.symbol);
        assertEquals("buy", result.side);
        assertTrue(result.shouldTrade);
        assertEquals(150.50, result.currentPrice);
    }

    @Test
    void failOnNullSymbol() {
        assertThrows(NullPointerException.class, () ->
            new SignalResult(null, "buy", true, 150.50));
    }

    @Test
    void failOnInvalidSide() {
        assertThrows(IllegalArgumentException.class, () ->
            new SignalResult("AAPL", "invalid_side", true, 150.50));
    }

    @Test
    void failOnNegativePrice() {
        assertThrows(IllegalArgumentException.class, () ->
            new SignalResult("AAPL", "buy", true, -1.0));
    }
}
