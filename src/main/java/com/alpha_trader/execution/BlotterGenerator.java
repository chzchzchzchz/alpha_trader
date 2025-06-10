package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.ZoneId;
import java.util.List;

/**
 * BlotterGenerator produces daily CSV at 23:59 ET.
 * <p>
 * Pass: writeBlotter() writes a CSV file with the provided rows for the current date in America/New_York timezone.
 * Fail: Throws IOException if the file cannot be written.
 * </p>
 */
public class BlotterGenerator {
    /**
     * Writes a daily blotter CSV file for the current date.
     * @param rows list of string arrays representing CSV rows
     * @throws IOException if the file cannot be written
     */
    public void writeBlotter(List<String[]> rows) throws IOException {
        ZonedDateTime now = ZonedDateTime.now(ZoneId.of("America/New_York"));
        String date = now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"));
        try (FileWriter fw = new FileWriter("reports/blotter_" + date + ".csv")) {
            for (String[] row : rows) {
                fw.write(String.join(",", row) + "\n");
            }
        }
    }
}
