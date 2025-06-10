package com.alpha_trader.jobs;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;

/**
 * ChecksumVerifier verifies file hashes nightly.
 * <p>
 * Pass: Exits 0 and logs "NO CHECKSUM ERRORS" if all files match their stored hashes.
 * Fail: Exits 1 if any file fails the stored hash list; logs the failed file(s).
 * </p>
 */
public class ChecksumVerifier {
    private static final String HASH_LIST = "config/config_hash.txt";

    /**
     * Main entry point for nightly checksum verification.
     * @param args command-line arguments
     * @throws Exception on I/O or hash errors
     */
    public static void main(String[] args) throws Exception {
        Map<String, String> expected = loadHashes();
        boolean anyFail = false;
        for (Map.Entry<String, String> entry : expected.entrySet()) {
            String file = entry.getKey();
            String expectedHash = entry.getValue();
            String actualHash = sha256(Files.readAllBytes(Paths.get(file)));
            if (!expectedHash.equals(actualHash)) {
                System.err.println("Checksum failed for: " + file);
                anyFail = true;
            }
        }
        if (anyFail) {
            System.exit(1);
        } else {
            System.out.println("NO CHECKSUM ERRORS");
        }
    }

    private static Map<String, String> loadHashes() throws IOException {
        Map<String, String> map = new HashMap<>();
        try (BufferedReader br = new BufferedReader(new FileReader(HASH_LIST))) {
            String line;
            while ((line = br.readLine()) != null) {
                String[] parts = line.split("\s+");
                if (parts.length == 2) {
                    map.put(parts[1], parts[0]);
                }
            }
        }
        return map;
    }

    private static String sha256(byte[] data) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] hash = md.digest(data);
        StringBuilder sb = new StringBuilder();
        for (byte b : hash) sb.append(String.format("%02x", b));
        return sb.toString();
    }
}
