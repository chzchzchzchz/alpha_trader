package alpha.core;

/**
 * DataHandler provides access to market data for strategies.
 * <p>
 * Pass: Implementations must provide price and bar access methods.
 * Fail: Any method throws if data is unavailable.
 * </p>
 */
public interface DataHandler {
    Double getLatestPrice(String symbol);
    Double getPreviousClose(String symbol);
    double[] getRecentCloses(String symbol, int limit);
    double[] getRecentHighs(String symbol, int limit);
}

