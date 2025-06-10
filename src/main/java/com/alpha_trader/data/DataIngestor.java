package com.alpha_trader.data;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * DataIngestor fetches bars from Alpaca REST, falling back to HistoricalCache on failure.
 * <p>
 * Pass: fetchBars() returns bars with timestamps aligned to whole-minute boundaries; falls back to HistoricalCache if Alpaca REST fails.
 * Fail: Throws UnsupportedOperationException if Alpaca REST is not implemented; returns only valid bars from cache on fallback.
 * </p>
 */
public class DataIngestor {
    private final HistoricalCache cache;

    public DataIngestor(HistoricalCache cache) {
        this.cache = cache;
    }

    /**
     * Fetches bars for the given symbol and time range, aligning timestamps to minute boundaries.
     * Falls back to HistoricalCache on REST failure.
     * @param symbol the symbol
     * @param from start time
     * @param to end time
     * @return list of aligned Bar objects
     */
    public List<Bar> fetchBars(String symbol, Instant from, Instant to) {
        try {
            // TODO: Replace with actual Alpaca REST call
            List<Bar> bars = fetchFromAlpaca(symbol, from, to);
            return alignBarsToMinute(bars);
        } catch (Exception e) {
            // Fallback to cache
            return alignBarsToMinute(cache.getBars(symbol, from, to));
        }
    }

    private List<Bar> fetchFromAlpaca(String symbol, Instant from, Instant to) throws Exception {
        // TODO: Implement Alpaca REST call
        throw new UnsupportedOperationException("Alpaca REST not implemented");
    }

    private List<Bar> alignBarsToMinute(List<Bar> bars) {
        return bars.stream()
            .map(bar -> new Bar(
                bar.getTimestamp().truncatedTo(ChronoUnit.MINUTES),
                bar.getOpen(),
                bar.getHigh(),
                bar.getLow(),
                bar.getClose(),
                bar.getVolume()
            ))
            .toList();
    }
}
