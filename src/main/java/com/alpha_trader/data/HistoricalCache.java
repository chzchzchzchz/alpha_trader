package com.alpha_trader.data;

import java.sql.*;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * HistoricalCache stores up to seven days of 1-min bars in SQLite.
 * <p>
 * Pass: getBars() returns bars sorted ascending by timestamp; upsertBar() uses INSERT OR REPLACE and rejects duplicate timestamp/symbol rows; cleanupOldData() deletes data older than seven days.
 * Fail: Throws RuntimeException on any SQL error; throws if DB is not writable.
 * </p>
 */
public class HistoricalCache {
    private static final String DB_PATH = "cache/historical.db";
    private static final long SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60;

    public HistoricalCache() {
        try (Connection conn = getConnection(); Statement stmt = conn.createStatement()) {
            stmt.executeUpdate("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, timestamp INTEGER, open REAL, high REAL, low REAL, close REAL, volume INTEGER, PRIMARY KEY(symbol, timestamp))");
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    /**
     * Inserts or replaces a bar for the given symbol. Rejects duplicate timestamp/symbol rows.
     * @param symbol the symbol
     * @param bar the Bar object
     * @throws RuntimeException on SQL error
     */
    public void upsertBar(String symbol, Bar bar) {
        String sql = "INSERT OR REPLACE INTO bars (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)";
        try (Connection conn = getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, symbol);
            ps.setLong(2, bar.getTimestamp().getEpochSecond());
            ps.setDouble(3, bar.getOpen());
            ps.setDouble(4, bar.getHigh());
            ps.setDouble(5, bar.getLow());
            ps.setDouble(6, bar.getClose());
            ps.setLong(7, bar.getVolume());
            ps.executeUpdate();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    /**
     * Returns bars for the given symbol and time range, sorted ascending by timestamp.
     * @param symbol the symbol
     * @param from start time (inclusive)
     * @param to end time (inclusive)
     * @return list of Bar objects
     * @throws RuntimeException on SQL error
     */
    public List<Bar> getBars(String symbol, Instant from, Instant to) {
        String sql = "SELECT timestamp, open, high, low, close, volume FROM bars WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC";
        List<Bar> bars = new ArrayList<>();
        try (Connection conn = getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, symbol);
            ps.setLong(2, from.getEpochSecond());
            ps.setLong(3, to.getEpochSecond());
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    bars.add(new Bar(
                        Instant.ofEpochSecond(rs.getLong(1)),
                        rs.getDouble(2),
                        rs.getDouble(3),
                        rs.getDouble(4),
                        rs.getDouble(5),
                        rs.getLong(6)
                    ));
                }
            }
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
        return Collections.unmodifiableList(bars);
    }

    /**
     * Deletes data older than seven days from the cache.
     * @throws RuntimeException on SQL error
     */
    public void cleanupOldData() {
        long cutoff = Instant.now().getEpochSecond() - SEVEN_DAYS_SECONDS;
        String sql = "DELETE FROM bars WHERE timestamp < ?";
        try (Connection conn = getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, cutoff);
            ps.executeUpdate();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    private Connection getConnection() throws SQLException {
        return DriverManager.getConnection("jdbc:sqlite:" + DB_PATH);
    }
}
