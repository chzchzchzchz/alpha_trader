package com.alpha_trader.execution;

/**
 * ESCalculator limits ES99 to < 5% of equity.
 * <p>
 * Pass: isESAllowed() returns true if ES99 < 5% of equity, false otherwise.
 * Fail: Returns false if ES99 ≥ 5% of equity.
 * </p>
 */
public class ESCalculator {
    /**
     * Checks if ES99 is allowed based on equity.
     * @param es99 the ES99 value
     * @param equity the equity value
     * @return true if ES99 < 5% of equity, false otherwise
     */
    public boolean isESAllowed(double es99, double equity) {
        return es99 < 0.05 * equity;
    }
}
