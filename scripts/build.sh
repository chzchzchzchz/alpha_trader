#!/usr/bin/env bash
set -e

# Build script for alpha_trader without Maven or sudo
# Compiles Java sources and runs tests using local JARs in lib/
# Usage: ./scripts/build.sh

# Set JAVA_HOME if needed (uncomment and set your path)
# export JAVA_HOME="$HOME/jdk-17"
# export PATH="$JAVA_HOME/bin:$PATH"

SRC_DIR="$(dirname "$0")/../src/main/java"
TEST_DIR="$(dirname "$0")/../src/test/java"
LIB_DIR="$(dirname "$0")/../lib"
BUILD_DIR="$(dirname "$0")/../build"

mkdir -p "$BUILD_DIR"

# Find all Java source files
find "$SRC_DIR" -name '*.java' > "$BUILD_DIR/sources.txt"

# Compile main sources
javac -d "$BUILD_DIR/classes" -cp "$LIB_DIR/*" -source 17 -target 17 -parameters -Xlint:all @"$BUILD_DIR/sources.txt"

# Compile tests if any
if [ -d "$TEST_DIR" ] && [ "$(find "$TEST_DIR" -name '*.java' | wc -l)" -gt 0 ]; then
  find "$TEST_DIR" -name '*.java' > "$BUILD_DIR/test_sources.txt"
  javac -d "$BUILD_DIR/test_classes" -cp "$LIB_DIR/*":"$BUILD_DIR/classes" -source 17 -target 17 -parameters -Xlint:all @"$BUILD_DIR/test_sources.txt"
fi

echo "Build complete."

