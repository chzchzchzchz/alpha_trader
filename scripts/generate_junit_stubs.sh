#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="src/main/java/com/alpha_trader"
TEST_DIR="src/test/java/com/alpha_trader"

find "$SRC_DIR" -name '*.java' | while read -r file; do
  rel="${file#$SRC_DIR/}"
  pkg_dir="$(dirname "$rel")"
  class="$(basename "$rel" .java)"
  test_path="$TEST_DIR/$pkg_dir/${class}Test.java"
  mkdir -p "$(dirname "$test_path")"
  [[ -f "$test_path" ]] && continue
  cat >"$test_path" <<EOF
package com.alpha_trader.${pkg_dir//\//.};

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ${class}Test {

  @Test
  void happyPath() {
    # TODO replace with real happy-path assertion
    assertTrue(true);
  }

  @Test
  void failurePath() {
    # TODO provoke and assert the expected exception
    assertThrows(RuntimeException.class,
      () -> { /* callable that must fail */ });
  }
}
EOF
done
