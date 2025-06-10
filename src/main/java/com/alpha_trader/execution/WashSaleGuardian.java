package com.alpha_trader.execution;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * WashSaleGuardian blocks sells within 30 days of a buy of the same symbol.
 * <p>
 * Pass: canSell() returns true only if no buy in last 30 days; recordBuy() tracks buys.
 * Fail: Returns false if attempting to sell within 30 days of a buy.
 * </p>
 */
public class WashSaleGuardian {
    private final Map<String, Instant> lastBuy = new HashMap<>();

    /**
     * Records a buy transaction for wash sale tracking.
     * @param symbol the stock symbol
     * @param time timestamp of the buy
     */
    public void recordBuy(String symbol, Instant time) {
        lastBuy.put(symbol, time);
    }

    /**
     * Checks if a sell is allowed without triggering a wash sale.
     * @param symbol the stock symbol
     * @param now current timestamp
     * @return true if no buy within last 30 days, false otherwise
     */
    public boolean canSell(String symbol, Instant now) {
        Instant buyTime = lastBuy.get(symbol);
        if (buyTime == null) return true;
        return now.isAfter(buyTime.plusSeconds(30L * 86400));
    }
}
