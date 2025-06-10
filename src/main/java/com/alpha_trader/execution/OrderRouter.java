package com.alpha_trader.execution;

import java.util.UUID;

/**
 * OrderRouter attaches a unique clientOrderId to every order.
 * <p>
 * Pass: sendOrder() generates and attaches a UUID as clientOrderId before routing.
 * Fail: Not implemented - will throw UnsupportedOperationException until order sending is complete.
 * </p>
 */
public class OrderRouter {
    /**
     * Sends an order with an automatically generated unique clientOrderId.
     * @param symbol the stock symbol
     * @param qty order quantity
     * @param price limit price
     * @throws UnsupportedOperationException until implementation is complete
     */
    public void sendOrder(String symbol, int qty, double price) {
        String clientOrderId = generateClientOrderId();
        // TODO: Implement order sending logic, attaching clientOrderId
    }

    private String generateClientOrderId() {
        return UUID.randomUUID().toString();
    }
}
