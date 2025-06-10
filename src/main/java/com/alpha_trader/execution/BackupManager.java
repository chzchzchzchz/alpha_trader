package com.alpha_trader.execution;

import javax.crypto.Cipher;
import javax.crypto.CipherOutputStream;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * BackupManager creates AES-256 tarball backups daily at 02:00 ET.
t 8 * <p>
 * Pass: createBackup() creates an encrypted tarball backup under backups/YYYY-MM-DD.tar.enc, excluding the backups directory itself.
 * Fail: Throws Exception on I/O or encryption errors.
 * </p>
 */
public class BackupManager {
    /**
     * Creates an AES-256 encrypted tarball backup.
     * @param passphraseFile path to the AES passphrase file
     * @throws Exception on I/O or encryption errors
     */
    public void createBackup(String passphraseFile) throws Exception {
        String date = new SimpleDateFormat("yyyy-MM-dd").format(new Date());
        String backupDir = "backups/";
        String tarPath = backupDir + date + ".tar";
        String encPath = backupDir + date + ".tar.enc";
        Files.createDirectories(Paths.get(backupDir));
        // Create tarball (zip for simplicity)
        try (ZipOutputStream zos = new ZipOutputStream(new FileOutputStream(tarPath))) {
            addDirToZip(new File("."), zos);
        }
        // Encrypt tarball
        byte[] keyBytes = Files.readAllBytes(Paths.get(passphraseFile));
        SecretKey key = new SecretKeySpec(keyBytes, 0, 32, "AES");
        Cipher cipher = Cipher.getInstance("AES");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        try (FileInputStream fis = new FileInputStream(tarPath);
             CipherOutputStream cos = new CipherOutputStream(new FileOutputStream(encPath), cipher)) {
            fis.transferTo(cos);
        }
        new File(tarPath).delete();
    }

    private void addDirToZip(File dir, ZipOutputStream zos) throws IOException {
        for (File file : dir.listFiles()) {
            if (file.isDirectory() && !file.getName().equals("backups")) {
                addDirToZip(file, zos);
            } else if (file.isFile()) {
                zos.putNextEntry(new ZipEntry(file.getPath()));
                try (FileInputStream fis = new FileInputStream(file)) {
                    fis.transferTo(zos);
                }
                zos.closeEntry();
            }
        }
    }
}
