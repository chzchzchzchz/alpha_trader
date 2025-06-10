package com.alpha_trader.execution;

/**
 * CorrelationGuard fails if average |ρ| > 0.6 among open positions.
 * <p>
 * Pass: checkAverageCorrelation() returns silently if average |ρ| ≤ 0.6.
 * Fail: Throws RuntimeException if average |ρ| > 0.6.
 * </p>
 */
public class CorrelationGuard {
    /**
     * Checks if the average absolute correlation among open positions exceeds 0.6.
     * @param correlations array of correlation coefficients
     * @throws RuntimeException if average |ρ| > 0.6
     */
    public void checkAverageCorrelation(double[] correlations) {
        double avgAbs = 0.0;
        for (double rho : correlations) {
            avgAbs += Math.abs(rho);
        }
        avgAbs /= correlations.length;
        if (avgAbs > 0.6) {
            throw new RuntimeException("CorrelationGuard fail: average |ρ| > 0.6");
        }
    }
}
