package com.alpha_trader.backtest;

/**
 * WalkForwardValidator throws WALK_FORWARD_FAIL if any window fails.
 */
public class WalkForwardValidator extends Exception {
    public WalkForwardValidator(String message) {
        super(message);
    }

    public static void validate(boolean[] windowResults) throws WalkForwardValidator {
        for (boolean pass : windowResults) {
            if (!pass) {
                throw new WalkForwardValidator("WALK_FORWARD_FAIL");
            }
        }
    }
}

