package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * RollingHeartbeat writes to heartbeat.txt every two seconds.
 * <p>
 * Pass: start() initiates scheduled writes to heartbeat.txt every 2 seconds.
 * Fail: Logs error if heartbeat file cannot be written.
 * </p>
 */
public class RollingHeartbeat {
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();

    /**
     * Starts the heartbeat writer, updating heartbeat.txt every 2 seconds.
     * Uses a single-threaded scheduler to maintain consistent timing.
     */
    public void start() {
        scheduler.scheduleAtFixedRate(this::writeHeartbeat, 0, 2, TimeUnit.SECONDS);
    }

    private void writeHeartbeat() {
        try (FileWriter fw = new FileWriter("heartbeat.txt")) {
            fw.write(Instant.now().toString());
        } catch (IOException e) {
            // Log error if needed
        }
    }
}
