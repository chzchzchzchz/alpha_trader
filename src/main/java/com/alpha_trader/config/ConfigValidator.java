package com.alpha_trader.config;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;

/**
 * ConfigValidator validates Alpaca keys/secrets and config values.
 * <p>
 * - Rejects keys not exactly 20 chars (throws IllegalArgumentException)
 * - Rejects secrets not 40 chars (throws IllegalArgumentException)
 * - Enforces VAR_THRESHOLD ≤ 0.03 (throws IllegalArgumentException)
 * </p>
 */
public final class ConfigValidator {

  private ConfigValidator() {}

  /**
   * Validates the Alpaca API key.
   * @param key the API key
   * @throws IllegalArgumentException if key is not exactly 20 characters
   */
  public static void validateKey(String key) {
    if (key == null || key.length() != 20)
      throw new IllegalArgumentException("API key must be exactly 20 chars");
  }

  /**
   * Validates the Alpaca API secret.
   * @param secret the API secret
   * @throws IllegalArgumentException if secret is not exactly 40 characters
   */
  public static void validateSecret(String secret) {
    if (secret == null || secret.length() != 40)
      throw new IllegalArgumentException("API secret must be exactly 40 chars");
  }

  /**
   * Validates the VAR_THRESHOLD value.
   * @param threshold the VAR_THRESHOLD value
   * @throws IllegalArgumentException if threshold > 0.03
   */
  public static void validateVarThreshold(double threshold) {
    if (threshold > 0.03)
      throw new IllegalArgumentException("VAR_THRESHOLD must be ≤ 0.03");
  }

  /** Verify SHA-256 of any config file against a trusted hex digest string. */
  public static void validateHash(Path file, String expectedSha256) throws Exception {
    byte[] raw = Files.readAllBytes(file);
    MessageDigest md = MessageDigest.getInstance("SHA-256");
    String actual = HexFormat.of().formatHex(md.digest(raw));
    if (!actual.equalsIgnoreCase(expectedSha256))
      throw new SecurityException("Config tamper detected: hash mismatch");
  }
}
