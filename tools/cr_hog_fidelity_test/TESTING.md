# Rudy fidelity tests: local and GitHub Actions

The same regression harness can now be viewed in two ways.

## GitHub Actions

Workflow: `.github/workflows/rudy-primary-pathing.yml`.

Open a run and use the **Summary** tab. It shows:

- video regression status for PRIMARY, d03 secondary and d02 cross-demo;
- real vs simulated Hog hit timestamps and per-hit deltas;
- Cannon/Hog death times and deltas;
- first divergence;
- solo-Hog guard metrics;
- bridge-routing guard metrics.

The artifact `rudy-postfix-regressions` still contains the complete JSON traces. It also contains `outputs/rudy_postfix/summary.md`, which is the same readable report shown in Actions.

## Local Windows run

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\cr_hog_fidelity_test\run_regressions_local.ps1
```

Requirements:

- `cr_engine` must be importable by the selected Python;
- Tournament-11 overlay must exist at `outputs/rudy_tournament11_data` (or pass another path with `-DataDir`).

Useful options:

```powershell
powershell -ExecutionPolicy Bypass -File tools\cr_hog_fidelity_test\run_regressions_local.ps1 `
  -Python py `
  -DataDir outputs\rudy_tournament11_data `
  -OutRoot outputs\rudy_local
```

Readable local report:

```text
outputs/rudy_local/summary.md
```

Full local JSON traces are kept below the same output directory.

A `DIFF` is a simulator-vs-video fidelity mismatch. It is intentionally reported instead of crashing the harness. Build/import/script errors remain actual failures.
