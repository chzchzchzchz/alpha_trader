package com.alpha_trader.backtest;

/**
 * FillSimulator calibrates base spread and impact coefficient.
 */
public class FillSimulator {
    private double baseSpread;
    private double impactCoefficient;

    public void calibrate(double[] fills) {
        // TODO: Implement calibration logic
        baseSpread = 0.01; // placeholder
        impactCoefficient = 0.1; // placeholder
    }

    public double getBaseSpread() {
        return baseSpread;
    }

    public double getImpactCoefficient() {
        return impactCoefficient;
    }
}

