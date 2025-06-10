package com.alpha_trader.execution;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;

/**
 * ConfigHashChecker aborts with code 13 on config hash mismatch.
 * <p>
 * Pass: check() exits silently if the config hash matches.
 * Fail: check() aborts the process with exit code 13 if the hash does not match.
 * </p>
 */
public class ConfigHashChecker {
    private static final String ENV_PATH = ".env";
    private static final String HASH_PATH = "config/config_hash.txt";

    /**
     * Checks the config hash and aborts with code 13 on mismatch.
     * @throws Exception on I/O or hash errors
     */
    public static void check() throws Exception {
        String envContent = new String(Files.readAllBytes(Paths.get(ENV_PATH)));
        String hash = sha256(envContent);
        String expectedHash = new String(Files.readAllBytes(Paths.get(HASH_PATH))).trim();
        if (!hash.equals(expectedHash)) {
            System.exit(13);
        }
    }

    private static String sha256(String s) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] hash = md.digest(s.getBytes());
        StringBuilder sb = new StringBuilder();
        for (byte b : hash) sb.append(String.format("%02x", b));
        return sb.toString();
    }
}
