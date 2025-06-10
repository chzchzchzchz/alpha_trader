package com.alpha_trader.backtest;

import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;

/**
 * LatencyLogger keeps the last 1,000 latency samples only and computes the 99th percentile ≤ 500 ms.
 */
public class LatencyLogger {
    private static final int MAX_SAMPLES = 1000;
    private final Deque<Long> samples = new ArrayDeque<>();

    /**
     * Logs a latency sample.
     *
     * @param latencyMs the latency in milliseconds
     */
    public void logSample(long latencyMs) {
        if (samples.size() == MAX_SAMPLES) {
            samples.removeFirst();
        }
        samples.addLast(latencyMs);
    }

    /**
     * Computes the 99th percentile of the logged latency samples.
     *
     * @return the 99th percentile latency in milliseconds
     */
    public double percentile99() {
        if (samples.isEmpty()) return 0;
        long[] arr = samples.stream().mapToLong(Long::longValue).toArray();
        Arrays.sort(arr);
        int idx = (int) Math.ceil(0.99 * arr.length) - 1;
        return arr[Math.max(0, idx)];
    }

    /**
     * Returns true if the 99th percentile latency is less than or equal to 500 ms.
     */
    public boolean isCompliant() {
        return percentile99() <= 500;
    }
}
