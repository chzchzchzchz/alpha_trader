package com.alpha_trader.execution;

/**
 * VaRCalculator limits parametric VaR95 to < 3% of equity.
 * <p>
 * Pass: isVaRAllowed() returns true if VaR95 < 3% of equity.
 * Fail: Returns false if VaR95 ≥ 3% of equity.
 * </p>
 */
public class VaRCalculator {
    /**
     * Checks if parametric VaR95 is within allowed limit.
     * @param var95 the VaR95 value
     * @param equity current equity value
     * @return true if VaR95 < 3% of equity, false otherwise
     */
    public boolean isVaRAllowed(double var95, double equity) {
        return var95 < 0.03 * equity;
    }
}
