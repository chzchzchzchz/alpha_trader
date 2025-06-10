package com.alpha_trader.execution;

import org.junit.jupiter.api.Test;
import java.io.IOException;
import java.lang.reflect.Field;

import static org.junit.jupiter.api.Assertions.*;

class LogRotatorTest {
    @Test
    void skipWhenDiskLow() throws IOException, NoSuchFieldException, IllegalAccessException {
        LogRotator rot = new LogRotator();
        // inject MIN_FREE via reflection to a huge value to simulate low disk
        Field f = LogRotator.class.getDeclaredField("MIN_FREE");
        f.setAccessible(true);
        f.setLong(null, Long.MAX_VALUE);
        rot.rotate("build/logs"); // should do nothing, not throw
    }
}

