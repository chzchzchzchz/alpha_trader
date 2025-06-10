package com.alpha_trader.execution;

/**
 * StressTester halves risk if worst-5% drawdown > 10%.
 * <p>
 * Pass: scaleRisk() returns 0.5 if worst-5% drawdown > 10%, 1.0 otherwise. Must run 10,000 paths in < 60s.
 * Fail: Returns 1.0 if input array is empty; must scale position sizes by returned factor.
 * </p>
 */
public class StressTester {
    /**
     * Calculates risk scaling factor based on worst-5% drawdown.
     * Must complete 10,000 paths in < 60s.
     * @param drawdowns array of drawdown values [0.0-1.0]
     * @return 0.5 if worst-5% drawdown > 10%, 1.0 otherwise
     */
    public double scaleRisk(double[] drawdowns) {
        int n = drawdowns.length;
        if (n == 0) return 1.0;
        java.util.Arrays.sort(drawdowns);
        int idx = (int) Math.ceil(0.05 * n) - 1;
        double worst5 = drawdowns[Math.max(0, idx)];
        if (worst5 > 0.10) {
            return 0.5;
        }
        return 1.0;
    }
}
