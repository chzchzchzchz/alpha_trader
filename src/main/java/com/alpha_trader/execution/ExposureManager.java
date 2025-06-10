package com.alpha_trader.execution;

import java.util.Map;

/**
 * ExposureManager blocks gross exposure > 110% of equity and sector exposure > 25% of equity.
 * <p>
 * Pass: isGrossExposureAllowed() and isSectorExposureAllowed() return true if exposures are within limits.
 * Fail: Return false if gross exposure > 110% or any sector > 25% of equity.
 * </p>
 */
public class ExposureManager {
    /**
     * Checks if gross exposure is allowed.
     * @param grossExposure gross exposure value
     * @param equity equity value
     * @return true if gross exposure ≤ 110% of equity, false otherwise
     */
    public boolean isGrossExposureAllowed(double grossExposure, double equity) {
        return grossExposure <= 1.10 * equity;
    }

    /**
     * Checks if sector exposures are allowed.
     * @param sectorExposure map of sector to exposure
     * @param equity equity value
     * @return true if all sectors ≤ 25% of equity, false otherwise
     */
    public boolean isSectorExposureAllowed(Map<String, Double> sectorExposure, double equity) {
        for (double exposure : sectorExposure.values()) {
            if (exposure > 0.25 * equity) {
                return false;
            }
        }
        return true;
    }
}
