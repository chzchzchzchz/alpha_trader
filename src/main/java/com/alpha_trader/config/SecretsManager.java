package com.alpha_trader.config;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * SecretsManager manages secrets, expiring them after 12 hours and throwing SECRET_EXPIRED.
 * <p>
 * - Stores secrets with timestamps
 * - Expires secrets after 12 hours (43200 seconds)
 * - Throws SecretExpiredException if expired
 * </p>
 */
public class SecretsManager {
    private static final long EXPIRY_SECONDS = 43200; // 12 hours
    private final Map<String, SecretEntry> secrets = new HashMap<>();

    /**
     * Stores a secret with the current timestamp.
     * @param key secret key
     * @param value secret value
     */
    public void putSecret(String key, String value) {
        secrets.put(key, new SecretEntry(value, Instant.now().getEpochSecond()));
    }

    /**
     * Retrieves a secret, throws SecretExpiredException if expired.
     * @param key secret key
     * @return secret value
     * @throws SecretExpiredException if secret is expired
     */
    public String getSecret(String key) throws SecretExpiredException {
        SecretEntry entry = secrets.get(key);
        if (entry == null) return null;
        long now = Instant.now().getEpochSecond();
        if (now - entry.timestamp > EXPIRY_SECONDS) {
            throw new SecretExpiredException("SECRET_EXPIRED");
        }
        return entry.value;
    }

    /**
     * Secret entry with value and timestamp.
     */
    private static class SecretEntry {
        String value;
        long timestamp;
        SecretEntry(String value, long timestamp) {
            this.value = value;
            this.timestamp = timestamp;
        }
    }

    /**
     * Exception thrown when a secret is expired.
     */
    public static class SecretExpiredException extends Exception {
        public SecretExpiredException(String msg) { super(msg); }
    }
}
