package com.alpha_trader.alert;

import java.io.FileWriter;
import java.io.IOException;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.ZoneId;

/**
 * DailyReporter writes a Markdown report at 16:05 ET.
 */
public class DailyReporter {
    public void writeReport(String content) throws IOException {
        ZonedDateTime now = ZonedDateTime.now(ZoneId.of("America/New_York"));
        String date = now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"));
        try (FileWriter fw = new FileWriter("reports/daily_report_" + date + ".md")) {
            fw.write(content);
        }
    }
}

