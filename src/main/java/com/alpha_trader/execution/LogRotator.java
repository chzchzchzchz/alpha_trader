package com.alpha_trader.execution;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.zip.GZIPOutputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;

/**
 * LogRotator gzips files > 50MB, retains 90 days, skips if disk free < 1GB.
 * <p>
 * Pass: rotate() compresses files > 50MB with gzip level 6, retains 90 days, skips if disk free < 1GB.
 * Fail: Throws IOException on compression or file operation errors.
 * </p>
 */
public class LogRotator {
    private static final long MAX_SIZE = 50L * 1024 * 1024;
    private static final long MIN_FREE = 1L * 1024 * 1024 * 1024;
    private static final long RETAIN_DAYS = 90L * 24 * 60 * 60;

    /**
     * Rotates log files in the specified directory.
     * Compresses files > 50MB with gzip level 6.
     * Skips rotation if disk free space < 1GB.
     * Deletes files older than 90 days.
     *
     * @param logDir directory containing log files
     * @throws IOException on compression or file operation errors
     */
    public void rotate(String logDir) throws IOException {
        File dir = new File(logDir);
        long free = new File("/").getFreeSpace();
        if (free < MIN_FREE) return; // skip rotation if disk tight
        for (File file : dir.listFiles()) {
            if (file.isFile() && file.length() > MAX_SIZE && !file.getName().endsWith(".gz")) {
                gzipFile(file);
            }
        }
        cleanupOld(dir);
    }

    private void gzipFile(File file) throws IOException {
        File gz = new File(file.getAbsolutePath() + ".gz");
        try (FileInputStream fis = new FileInputStream(file);
             GZIPOutputStream gos = new GZIPOutputStream(new FileOutputStream(gz)) {
                 { def.setLevel(6); }
             }) {
            fis.transferTo(gos);
        }
        file.delete();
    }

    private void cleanupOld(File dir) {
        long cutoff = Instant.now().getEpochSecond() - RETAIN_DAYS;
        for (File file : dir.listFiles()) {
            if (file.isFile() && file.lastModified() / 1000 < cutoff) {
                file.delete();
            }
        }
    }
}
