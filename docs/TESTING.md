# Testing

Each case under [tests/fixtures/scan/](../tests/fixtures/scan/) has an answer key written by hand
that grades every usage: migrated, or left and why. The first five were written before the scanner
existed. The suite reproduces every key, and each rewritten file matches its expected file byte for
byte. [tests/fixtures/scan/COVERAGE.md](../tests/fixtures/scan/COVERAGE.md) lists 38 gaps the
fixtures do not cover, 20 of them closed. CI runs the suite on Linux for every supported Python and
on macOS and Windows for the oldest, the newest and 3.14, and holds each system to 100% branch
coverage of the code it runs.

The [benchmark](BENCHMARK.md) measures the same code on public repositories, and
[CONTRIBUTING.md](../CONTRIBUTING.md) says how to run the suite.
