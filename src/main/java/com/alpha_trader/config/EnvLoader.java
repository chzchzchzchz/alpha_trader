package com.alpha_trader.config;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Properties;
import java.util.logging.Logger;
import java.util.logging.Level;

/**
 * EnvLoader loads environment variables from the .env file at project root.
 * Fails with exit code 13 on config hash mismatch unless --override is present.
 */
public class EnvLoader {
    private static final Logger logger = Logger.getLogger(EnvLoader.class.getName());
    private static final String ENV_PATH = ".env";
    private static final String HASH_PATH = "config/config_hash.txt";
    private static final int EXIT_CODE_HASH_MISMATCH = 13;

    public static void loadEnv(String[] args) {
        Properties props = new Properties();
        try (FileInputStream fis = new FileInputStream(ENV_PATH)) {
            props.load(fis);
        } catch (IOException e) {
            logger.log(Level.SEVERE, "Failed to load .env file: {0}", e.getMessage());
            System.exit(EXIT_CODE_HASH_MISMATCH);
        }
        // Set as system properties
        for (String key : props.stringPropertyNames()) {
            System.setProperty(key, props.getProperty(key));
        }
        // Check config hash
        if (!hasOverride(args)) {
            try {
                String envContent = new String(Files.readAllBytes(Paths.get(ENV_PATH)), StandardCharsets.UTF_8);
                String hash = sha256(envContent);
                String expectedHash = readExpectedHash();
                if (!hash.equals(expectedHash)) {
                    logger.severe("Config hash mismatch. Aborting.");
                    System.exit(EXIT_CODE_HASH_MISMATCH);
                }
            } catch (Exception e) {
                logger.log(Level.SEVERE, "Error checking config hash: {0}", e.getMessage());
                System.exit(EXIT_CODE_HASH_MISMATCH);
            }
        }
    }

    private static boolean hasOverride(String[] args) {
        for (String arg : args) {
            if ("--override".equals(arg)) return true;
        }
        return false;
    }

    private static String sha256(String input) throws NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder hexString = new StringBuilder();
        for (byte b : hash) {
            String hex = Integer.toHexString(0xff & b);
            if (hex.length() == 1) hexString.append('0');
            hexString.append(hex);
        }
        return hexString.toString();
    }

    private static String readExpectedHash() throws IOException {
        for (String line : Files.readAllLines(Paths.get(HASH_PATH), StandardCharsets.UTF_8)) {
            line = line.trim();
            if (!line.isEmpty() && !line.startsWith("#")) {
                return line;
            }
        }
        return "";
    }
}
