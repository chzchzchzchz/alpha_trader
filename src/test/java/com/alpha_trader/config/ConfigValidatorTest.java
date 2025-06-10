package com.alpha_trader.config;

import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

class ConfigValidatorTest {

  @Test
  void acceptsValidKeyAndSecret() {
    assertDoesNotThrow(() -> {
      ConfigValidator.validateKey("ABCDEFGHIJKLMNOPQRST");      // 20
      ConfigValidator.validateSecret("ABCDEFGHIJKLMNOPQRST0123456789ABCDEFGH"); // 40
      ConfigValidator.validateVarThreshold(0.02);
    });
  }

  @Test
  void rejectsInvalidValues() {
    assertAll(
      () -> assertThrows(IllegalArgumentException.class,
            () -> ConfigValidator.validateKey("SHORT")),
      () -> assertThrows(IllegalArgumentException.class,
            () -> ConfigValidator.validateSecret("TOO-SHORT")),
      () -> assertThrows(IllegalArgumentException.class,
            () -> ConfigValidator.validateVarThreshold(0.99))
    );
  }

  @Test
  void detectsHashMismatch() throws Exception {
    Path tmp = Files.createTempFile("cfg", ".txt");
    Files.writeString(tmp, "evil change");
    assertThrows(SecurityException.class,
         () -> ConfigValidator.validateHash(tmp, "DEADBEEF"));
  }
}
