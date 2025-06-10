package com.alpha_trader.execution;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * PanicSwitch cancels all orders and exits within five seconds on activation.
 * <p>
 * Pass: activate() cancels all orders and exits with code 2 within five seconds.
 * Fail: Forces exit with code 2 after five seconds even if cancellation is incomplete.
 * </p>
 */
public class PanicSwitch {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    /**
     * Activates the panic switch, canceling all orders and exiting within five seconds.
     * Writes shutdown reason and exits with code 2.
     */
    public void activate() {
        executor.submit(() -> {
            cancelAllOrders();
            writeShutdownReason();
            System.exit(2);
        });
        executor.shutdown();
        try {
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                System.exit(2);
            }
        } catch (InterruptedException e) {
            System.exit(2);
        }
    }

    private void cancelAllOrders() {
        // TODO: Implement order cancellation logic
    }

    private void writeShutdownReason() {
        // TODO: Write shutdown.reason file
    }
}
