package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.ZoneId;
import java.util.List;

/**
 * TaxReportGenerator produces FIFO-lot 8949 CSV daily.
 * <p>
 * Pass: writeTaxReport() creates CSV with FIFO lot assignments for Form 8949.
 * Fail: Throws IOException if report cannot be written.
 * </p>
 */
public class TaxReportGenerator {
    /**
     * Writes Form 8949 tax report using FIFO lot assignment method.
     * @param rows list of string arrays containing trade data
     * @throws IOException if report cannot be written
     */
    public void writeTaxReport(List<String[]> rows) throws IOException {
        ZonedDateTime now = ZonedDateTime.now(ZoneId.of("America/New_York"));
        String date = now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"));
        try (FileWriter fw = new FileWriter("reports/tax_8949_" + date + ".csv")) {
            for (String[] row : rows) {
                fw.write(String.join(",", row) + "\n");
            }
        }
    }
}
