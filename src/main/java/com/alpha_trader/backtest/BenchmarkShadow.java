package com.alpha_trader.backtest;

/**
 * BenchmarkShadow compares against SPUS and requires +0.2 Sharpe spread.
 */
public class BenchmarkShadow {
    public void compareSharpe(double strategySharpe, double spusSharpe) {
        if (strategySharpe < spusSharpe + 0.2) {
            throw new RuntimeException("BenchmarkShadow failed: Sharpe spread < 0.2");
        }
    }
}

