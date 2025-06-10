package com.alpha_trader.execution;

/**
 * StopLossManager sets per-trade stop at 1% of entry price.
 * <p>
 * Pass: calculateStopLoss() returns exactly 99% of entry price.
 * Fail: Throws IllegalArgumentException if entry price is negative or zero.
 * </p>
 */
public class StopLossManager {
    /**
     * Calculates stop loss price at 1% below entry.
     * @param entryPrice entry price of the trade
     * @return stop loss price (99% of entry)
     * @throws IllegalArgumentException if entry price ≤ 0
     */
    public double calculateStopLoss(double entryPrice) {
        if (entryPrice <= 0) {
            throw new IllegalArgumentException("Entry price must be positive");
        }
        return entryPrice * 0.99;
    }
}
