package com.alpha_trader.execution;

import java.time.Instant;
import java.util.Timer;
import java.util.TimerTask;

/**
 * HaltManager detects halt status via Alpaca every 60 seconds.
 * <p>
 * Pass: isHalted() returns true if halt detected, false otherwise. Checks every 60 seconds.
 * Fail: If Alpaca API call fails, status may be stale.
 * </p>
 */
public class HaltManager {
    private boolean halted = false;
    private final Timer timer = new Timer(true);

    public HaltManager() {
        timer.scheduleAtFixedRate(new TimerTask() {
            @Override
            public void run() {
                checkHaltStatus();
            }
        }, 0, 60_000);
    }

    private void checkHaltStatus() {
        // TODO: Implement Alpaca API call to check halt status
        // Set halted = true if halted, else false
    }

    /**
     * Returns whether the system is currently halted.
     * @return true if halted, false otherwise
     */
    public boolean isHalted() {
        return halted;
    }
}
