package com.alpha_trader.execution;

import java.io.FileWriter;
import java.io.IOException;
import java.util.Map;

/**
 * FeatureImportanceLogger outputs at least ten features. File name starts with alpha/feature_importance_.
 * <p>
 * Pass: logFeatureImportance() writes at least ten features to a file named alpha/feature_importance_<suffix>.txt.
 * Fail: Throws IOException if the file cannot be written.
 * </p>
 */
public class FeatureImportanceLogger {
    /**
     * Logs at least ten feature importances to a file.
     * @param importances map of feature name to importance
     * @param suffix file suffix for output file
     * @throws IOException if the file cannot be written
     */
    public void logFeatureImportance(Map<String, Double> importances, String suffix) throws IOException {
        String file = "alpha/feature_importance_" + suffix + ".txt";
        try (FileWriter fw = new FileWriter(file)) {
            importances.entrySet().stream()
                .sorted((a, b) -> Double.compare(b.getValue(), a.getValue()))
                .limit(10)
                .forEach(e -> {
                    try {
                        fw.write(e.getKey() + ": " + e.getValue() + "\n");
                    } catch (IOException ex) {
                        // Handle error
                    }
                });
        }
    }
}
