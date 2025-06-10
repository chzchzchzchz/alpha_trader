package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.time.Instant;
import java.util.List;

/**
 * StateSnapshot file is updated every 60 s and includes open positions and orders.
 * <p>
 * Pass: writeSnapshot() writes current positions and orders with timestamp to state_snapshot.txt.
 * Fail: Throws IOException if snapshot cannot be written to file.
 * </p>
 */
public class StateSnapshot {
    /**
     * Writes current positions and orders to state snapshot file.
     * Must be called every 60 seconds by scheduler.
     * @param positions list of current position strings
     * @param orders list of current order strings
     * @throws IOException if snapshot cannot be written
     */
    public void writeSnapshot(List<String> positions, List<String> orders) throws IOException {
        try (FileWriter fw = new FileWriter("state_snapshot.txt")) {
            fw.write("Timestamp: " + Instant.now().toString() + "\n");
            fw.write("Positions:\n");
            for (String pos : positions) fw.write(pos + "\n");
            fw.write("Orders:\n");
            for (String ord : orders) fw.write(ord + "\n");
        }
    }
}
