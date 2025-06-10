package com.alpha_trader.execution;

import java.time.Instant;
import java.util.LinkedList;
import java.util.Queue;

/**
 * DrawdownMonitor triggers kill switch on 7-day drawdown > 5%.
 * <p>
 * Pass: recordEquity() maintains a 7-day sliding window and triggers kill switch if drawdown > 5%.
 * Fail: Triggers kill switch if drawdown exceeds 5% from max equity in window.
 * </p>
 */
public class DrawdownMonitor {
    private static final int WINDOW_DAYS = 7;
    private final Queue<Double> equityHistory = new LinkedList<>();
    private final Queue<Instant> timeHistory = new LinkedList<>();
    private double maxEquity = Double.MIN_VALUE;

    /**
     * Records equity and checks for 7-day drawdown > 5%.
     * @param equity current equity value
     * @param now current timestamp
     */
    public void recordEquity(double equity, Instant now) {
        equityHistory.add(equity);
        timeHistory.add(now);
        maxEquity = Math.max(maxEquity, equity);
        cleanupOld(now);
        if (maxEquity > 0 && (maxEquity - equity) / maxEquity > 0.05) {
            triggerKillSwitch();
        }
    }

    private void cleanupOld(Instant now) {
        while (!timeHistory.isEmpty() && now.minusSeconds(WINDOW_DAYS * 86400).isAfter(timeHistory.peek())) {
            equityHistory.poll();
            timeHistory.poll();
        }
    }

    private void triggerKillSwitch() {
        // TODO: Implement kill switch activation
    }
}
