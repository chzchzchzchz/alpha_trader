package com.alpha_trader.strategy;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;

/**
 * StrategyDeployer verifies jarHash before copying to execution/strategies.
 * <p>
 * Pass: deploy() copies the JAR to execution/strategies/ if the hash matches.
 * Fail: Throws RuntimeException if the hash does not match or file operations fail.
 * </p>
 */
public class StrategyDeployer {
    /**
     * Deploys a strategy JAR after verifying its SHA-256 hash.
     * @param jarPath path to the JAR file
     * @param expectedHash expected SHA-256 hash (hex, lower-case)
     * @throws Exception if hash does not match or file operations fail
     */
    public void deploy(String jarPath, String expectedHash) throws Exception {
        String actualHash = sha256(Files.readAllBytes(new File(jarPath).toPath()));
        if (!expectedHash.equals(actualHash)) {
            throw new RuntimeException("jarHash mismatch");
        }
        File dest = new File("execution/strategies/" + new File(jarPath).getName());
        Files.copy(new File(jarPath).toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }

    private String sha256(byte[] data) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] hash = md.digest(data);
        StringBuilder sb = new StringBuilder();
        for (byte b : hash) sb.append(String.format("%02x", b));
        return sb.toString();
    }
}
