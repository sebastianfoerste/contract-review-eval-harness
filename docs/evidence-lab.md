# Evidence Lab (web explorer) and parity vectors

Moved from the README.

## Interactive Web Explorer: Evidence Lab

The companion web app, `contract-eval-web`, lets you explore these cases in a browser without installing Python or calling a live model. It is maintained in a separate repository that is not public yet.

- **Features**: inspect the synthetic contracts, switch between the *baseline*, *no-evidence*, *missed-risks* and *conflicting-flags* scenarios, compare scores side by side, inspect quote grounding, and download Markdown or JSON reports.
- **Scoring parity**: the web app ports `score_review` to TypeScript. Its tests check the port against vectors this harness computes for every case and scenario. That covers the bounded public inputs, not arbitrary documents.
- **Sync**: with `contract-eval-web` checked out next to this repository, `make web-export` regenerates its dataset and parity vectors from the committed harness inputs, and `make web-check` fails if they have drifted.
- **CI gate**: the same vectors are committed as `examples/web-parity-vectors.json`. `make parity-check` runs in CI without the web repository and fails when a scorer or fixture change alters them; `make parity-vectors` regenerates the file for an intended change.

