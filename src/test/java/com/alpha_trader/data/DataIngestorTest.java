package com.alpha_trader.data;

import org.junit.jupiter.api.Test;
import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DataIngestorTest {
    @Test
    void happyPath() {
        // Arrange: mock HistoricalCache to never be used
        HistoricalCache cache = new HistoricalCache() {
            @Override
            public List<Bar> getBars(String symbol, Instant from, Instant to) {
                fail("Should not call cache in happy path");
                return Collections.emptyList();
            }
        };
        DataIngestor ingestor = new DataIngestor(cache) {
            public List<Bar> fetchFromAlpaca(String symbol, Instant from, Instant to) {
                // Simulate Alpaca REST success
                return Arrays.asList(
                    new Bar(from, 1, 2, 0.5, 1.5, 100)
                );
            }
        };
        // Act
        List<Bar> bars = ingestor.fetchBars("AAPL", Instant.now(), Instant.now().plusSeconds(60));
        // Assert
        assertEquals(1, bars.size());
        assertEquals(1, bars.get(0).getOpen());
    }

    @Test
    void failurePath() {
        // Arrange: mock HistoricalCache to return fallback data
        Bar fallbackBar = new Bar(Instant.now(), 10, 12, 9, 11, 200);
        HistoricalCache cache = new HistoricalCache() {
            @Override
            public List<Bar> getBars(String symbol, Instant from, Instant to) {
                return Arrays.asList(fallbackBar);
            }
        };
        DataIngestor ingestor = new DataIngestor(cache) {
            public List<Bar> fetchFromAlpaca(String symbol, Instant from, Instant to) throws Exception {
                throw new UnsupportedOperationException("Simulated REST failure");
            }
        };
        // Act
        List<Bar> bars = ingestor.fetchBars("AAPL", Instant.now(), Instant.now().plusSeconds(60));
        // Assert
        assertEquals(1, bars.size());
        assertEquals(10, bars.get(0).getOpen());
    }
}
