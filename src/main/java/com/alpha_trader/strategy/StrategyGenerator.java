package com.alpha_trader.strategy;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;

/**
 * StrategyGenerator writes strategy skeletons into alpha/candidates.
 * <p>
 * Pass: generateStrategy() creates a Java class file with a name starting with GeneratedStrategy_ in the output directory.
 * Fail: Throws IOException if file cannot be written or directory cannot be created.
 * </p>
 */
public class StrategyGenerator {
    private static final String OUTPUT_DIR = "alpha/candidates";

    /**
     * Generates a strategy skeleton Java file with the specified name.
     * @param name the base name for the strategy class
     * @throws IOException if file or directory cannot be created
     */
    public void generateStrategy(String name) throws IOException {
        if (!name.startsWith("GeneratedStrategy_")) {
            name = "GeneratedStrategy_" + name;
        }
        File dir = new File(OUTPUT_DIR);
        if (!dir.exists()) dir.mkdirs();
        File file = new File(dir, name + ".java");
        try (FileWriter fw = new FileWriter(file)) {
            fw.write("package alpha.candidates;\n\n");
            fw.write("public class " + name + " implements alpha.core.BaseStrategy {\n");
            fw.write("    // TODO: Implement strategy methods\n");
            fw.write("}\n");
        }
    }
}
