package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;

/**
 * AuditLogger hash-chains every entry and detects tampering.
 * <p>
 * Pass: log() appends a hash-chained entry to the audit log; verify() returns true if the log is untampered.
 * Fail: Throws Exception on I/O or hash errors; verify() returns false if tampering is detected.
 * </p>
 */
public class AuditLogger {
    private static final String LOG_PATH = "security/audit.log";
    private String lastHash = "";

    public AuditLogger() {
        try {
            if (Files.exists(Paths.get(LOG_PATH))) {
                lastHash = getLastHash();
            }
        } catch (IOException e) {
            lastHash = "";
        }
    }

    /**
     * Appends a hash-chained entry to the audit log.
     * @param entry the log entry
     * @throws Exception on I/O or hash errors
     */
    public void log(String entry) throws Exception {
        String newHash = sha256(lastHash + entry);
        try (FileWriter fw = new FileWriter(LOG_PATH, true)) {
            fw.write(newHash + " " + entry + "\n");
        }
        lastHash = newHash;
    }

    /**
     * Verifies the audit log for tampering.
     * @return true if untampered, false otherwise
     * @throws Exception on I/O or hash errors
     */
    public boolean verify() throws Exception {
        String prev = "";
        for (String line : Files.readAllLines(Paths.get(LOG_PATH))) {
            String[] parts = line.split(" ", 2);
            if (parts.length != 2) return false;
            String expected = sha256(prev + parts[1]);
            if (!expected.equals(parts[0])) return false;
            prev = parts[0];
        }
        return true;
    }

    private String getLastHash() throws IOException {
        String last = "";
        for (String line : Files.readAllLines(Paths.get(LOG_PATH))) {
            String[] parts = line.split(" ", 2);
            if (parts.length == 2) last = parts[0];
        }
        return last;
    }

    private String sha256(String s) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] hash = md.digest(s.getBytes());
        StringBuilder sb = new StringBuilder();
        for (byte b : hash) sb.append(String.format("%02x", b));
        return sb.toString();
    }
}
