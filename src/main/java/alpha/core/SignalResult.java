package alpha.core;

import java.util.Objects;
import java.util.Set;

/**
 * SignalResult represents the output of a strategy's signal generation.
 * <p>
 * Pass: Contains symbol, side, shouldTrade, and currentPrice fields.
 * Fail: Throws IllegalArgumentException if side is invalid or price is negative.
 *       Throws NullPointerException if symbol or side is null.
 * </p>
 */
public class SignalResult {
    private static final Set<String> VALID_SIDES = Set.of("buy", "sell");

    public final String symbol;
    public final String side;
    public final boolean shouldTrade;
    public final double currentPrice;

    /**
     * Creates a new SignalResult with validation.
     * @param symbol The trading symbol, must not be null
     * @param side Must be either "buy" or "sell"
     * @param shouldTrade Whether the signal indicates a trade
     * @param currentPrice Must be positive
     * @throws NullPointerException if symbol or side is null
     * @throws IllegalArgumentException if side is invalid or price is negative
     */
    public SignalResult(String symbol, String side, boolean shouldTrade, double currentPrice) {
        this.symbol = Objects.requireNonNull(symbol, "Symbol cannot be null");
        this.side = Objects.requireNonNull(side, "Side cannot be null");

        if (!VALID_SIDES.contains(side)) {
            throw new IllegalArgumentException("Side must be either 'buy' or 'sell'");
        }
        if (currentPrice <= 0) {
            throw new IllegalArgumentException("Price must be positive");
        }

        this.shouldTrade = shouldTrade;
        this.currentPrice = currentPrice;
    }
}
