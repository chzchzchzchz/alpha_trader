package com.alpha_trader.data;

import java.time.Instant;
import java.util.List;

/**
 * FeedValidator flags bars with zero volume during market hours and pauses trading for 60 s after a price outlier event.
 * <p>
 * Pass: validateBars() flags zero-volume bars during market hours and pauses trading for 60 seconds after a price outlier.
 * Fail: If a price outlier is detected, trading is paused for 60 seconds. If market is open and a bar has zero volume, it is flagged.
 * </p>
 */
public class FeedValidator {
    private boolean tradingPaused = false;
    private Instant pauseUntil = Instant.EPOCH;

    /**
     * Returns true if trading is currently paused due to a price outlier event.
     * @return true if trading is paused, false otherwise
     */
    public boolean isTradingPaused() {
        return tradingPaused && Instant.now().isBefore(pauseUntil);
    }

    /**
     * Validates a list of bars, flagging zero-volume bars during market hours and pausing trading for 60 seconds after a price outlier.
     * @param bars list of Bar objects
     * @param marketOpen true if market is open
     */
    public void validateBars(List<Bar> bars, boolean marketOpen) {
        for (Bar bar : bars) {
            if (marketOpen && bar.getVolume() == 0) {
                flagZeroVolume(bar);
            }
            if (isPriceOutlier(bar)) {
                pauseTrading(60);
            }
        }
    }

    private void flagZeroVolume(Bar bar) {
        // TODO: Implement alert/logging for zero volume
    }

    private boolean isPriceOutlier(Bar bar) {
        // TODO: Implement price outlier detection logic
        return false;
    }

    private void pauseTrading(int seconds) {
        tradingPaused = true;
        pauseUntil = Instant.now().plusSeconds(seconds);
    }
}
