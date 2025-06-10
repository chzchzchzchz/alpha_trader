package com.alpha_trader.data;

import java.time.Instant;

/**
 * Immutable Bar class representing a single OHLCV bar with timestamp.
 * <p>
 * Pass: All fields are set at construction and cannot be changed.
 * Fail: Throws NullPointerException if timestamp is null.
 * </p>
 */
public final class Bar {
    private final Instant timestamp;
    private final double open;
    private final double high;
    private final double low;
    private final double close;
    private final long volume;

    /**
     * Constructs a Bar instance with the given parameters.
     *
     * @param timestamp the timestamp of the bar, must not be null
     * @param open      the opening price
     * @param high      the highest price
     * @param low       the lowest price
     * @param close     the closing price
     * @param volume    the volume
     * @throws NullPointerException if timestamp is null
     */
    public Bar(Instant timestamp, double open, double high, double low, double close, long volume) {
        this.timestamp = timestamp;
        this.open = open;
        this.high = high;
        this.low = low;
        this.close = close;
        this.volume = volume;
    }

    public Instant getTimestamp() {
        return timestamp;
    }

    public double getOpen() {
        return open;
    }

    public double getHigh() {
        return high;
    }

    public double getLow() {
        return low;
    }

    public double getClose() {
        return close;
    }

    public long getVolume() {
        return volume;
    }
}
