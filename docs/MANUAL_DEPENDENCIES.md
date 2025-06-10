# Manual Dependency Setup for alpha_trader (No Maven/Homebrew)

## Java
- Download and extract a portable JDK 17 (e.g. from https://adoptium.net/) if not already installed. No admin/sudo required.
- Set JAVA_HOME and add to PATH if needed.

## Java JARs
Place the following JARs in the lib/ directory at project root:

- sqlite-jdbc-3.45.0.0.jar (https://repo1.maven.org/maven2/org/xerial/sqlite-jdbc/3.45.0.0/)
- simpleclient-0.16.0.jar (https://repo1.maven.org/maven2/io/prometheus/simpleclient/0.16.0/)
- jackson-databind-2.14.3.jar (https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.14.3/)
- jakarta.mail-2.1.1.jar (https://repo1.maven.org/maven2/jakarta/mail/jakarta.mail/2.1.1/)
- junit-jupiter-api-5.10.2.jar (https://repo1.maven.org/maven2/org/junit/jupiter/junit-jupiter-api/5.10.2/) [for tests]
- mockito-core-5.2.0.jar (https://repo1.maven.org/maven2/org/mockito/mockito-core/5.2.0/) [for tests]
- junit-platform-console-standalone-1.10.2.jar (https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/1.10.2/) [for running tests]

Download these JARs directly and place them in alpha_trader/lib/.

## Python
- Install Python 3.9+ (no sudo required; use pyenv or download from python.org if needed).
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
  All dependencies are pinned to exact versions in requirements.txt.

## No Maven, Homebrew, or admin/sudo required at any step.
