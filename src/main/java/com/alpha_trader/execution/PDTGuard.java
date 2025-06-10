package com.alpha_trader.execution;

import java.time.Instant;
import java.util.LinkedList;

/**
 * PDTGuard blocks the 4th day-trade in five rolling trading days.
 * <p>
 * Pass: canTrade() returns true if &lt; 3 day trades in 5 rolling days; recordDayTrade() tracks trades.
 * Fail: Returns false on 4th attempted day trade within rolling window.
 * </p>
 */
public class PDTGuard {
    private final LinkedList<Instant> dayTrades = new LinkedList<>();

    /**
     * Checks if a day trade can be made without violating PDT rule.
     *
     * @param now current timestamp
     * @return true if trade allowed, false if would exceed 3 day trades in 5 days
     */
    public boolean canTrade(Instant now) {
        cleanupOld(now);
        return dayTrades.size() < 3;
    }

    /**
     * Records a day trade at the given timestamp.
     *
     * @param now timestamp of the day trade
     */
    public void recordDayTrade(Instant now) {
        cleanupOld(now);
        dayTrades.add(now);
    }

    private void cleanupOld(Instant now) {
        while (!dayTrades.isEmpty() && now.minusSeconds(5L * 86400).isAfter(dayTrades.peek())) {
            dayTrades.poll();
        }
    }
}
