# Security

This is an evaluation harness for demonstration, built on synthetic contracts.

- All contracts under `data/` are fabricated. No real agreement or client data.
- The default path makes no network calls and needs no API key — it runs the deterministic stub adapter against bundled fixtures.
- The optional `--live` adapter calls the Anthropic API and reads `ANTHROPIC_API_KEY` from the environment. No key is stored, logged, or committed. The Anthropic SDK is an optional, lazily imported dependency.

If you find a security issue (for example, a dependency advisory), open an issue on the
repository. There is no real data and no deployment surface, so there is no
sensitive-disclosure path.
