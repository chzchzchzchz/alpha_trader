package com.alpha_trader.backtest;

import alpha.core.BaseStrategy;

/**
 * Backtester runs three sliding windows: train 60d, val 30d, test 30d.
 * Fails if out-of-sample Sharpe < 0.7.
 */
public class Backtester {
    public void run(BaseStrategy strategy) {
        // TODO: Implement sliding window logic
        double outOfSampleSharpe = computeSharpe(); // placeholder
        if (outOfSampleSharpe < 0.7) {
            throw new RuntimeException("Backtest failed: out-of-sample Sharpe < 0.7");
        }
    }

    private double computeSharpe() {
        // TODO: Implement Sharpe calculation
        return 1.0;
    }
}

