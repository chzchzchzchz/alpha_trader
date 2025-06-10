package alpha.core;

/**
 * BaseStrategy defines the interface for all trading strategies.
 * <p>
 * Pass: Implementations must provide generateSignal() and getSymbols().
 * Fail: Any unimplemented method throws UnsupportedOperationException.
 * </p>
 */
public interface BaseStrategy {
    /**
     * Generates a trading signal for the strategy.
     * @return SignalResult object or null if no signal
     */
    SignalResult generateSignal();

    /**
     * Returns the list of symbols this strategy trades.
     * @return array of symbols
     */
    String[] getSymbols();
}
