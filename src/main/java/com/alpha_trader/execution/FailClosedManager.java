package com.alpha_trader.execution;

/**
 * FailClosedManager sets tradingEnabled=false after three consecutive 5xx errors.
 * <p>
 * Pass: isTradingEnabled() returns true unless three consecutive 5xx errors have occurred.
 * Fail: Sets tradingEnabled=false after three consecutive 5xx errors.
 * </p>
 */
public class FailClosedManager {
    private int consecutive5xx = 0;
    private boolean tradingEnabled = true;

    /**
     * Handles API response and disables trading after three consecutive 5xx errors.
     * @param statusCode HTTP status code from API response
     */
    public void onApiResponse(int statusCode) {
        if (statusCode >= 500 && statusCode < 600) {
            consecutive5xx++;
            if (consecutive5xx >= 3) {
                tradingEnabled = false;
            }
        } else {
            consecutive5xx = 0;
        }
    }

    /**
     * Returns whether trading is currently enabled.
     * @return true if trading is enabled, false otherwise
     */
    public boolean isTradingEnabled() {
        return tradingEnabled;
    }
}
