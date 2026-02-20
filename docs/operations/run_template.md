# Run Template (Fill This For Any “Real” Run)

> Goal: prevent “experiment now, archaeology later”.
>
> Keep this file lightweight but **decision complete**: someone else should be able
> to reproduce your run without asking you anything.

## 0) Metadata

- Run name / tag:
- Date:
- Owner:
- Type: (smoke / full / sweep / ablation / benchmark)
- Dataset + split:
- Modality: (lidar / camera / fusion)
- Canonical? (yes/no; if no, why)

## 1) Code Provenance (Must)

- Main repo commit: `git rev-parse HEAD`
- Submodules:
  - `HEAL` commit: `git -C HEAL rev-parse HEAD` (if used)
  - other submodules:
- Dirty status at run time:
  - main: (clean / dirty + summary)
  - HEAL: (clean / dirty + summary)

## 2) Inputs (Must)

- Config path:
- Data roots / caches (exact paths):
  - `data_root`:
  - `data_info_path`:
  - stage1 / detection cache:
- Noise / dropout:
- Any extra artifacts:
  - (e.g. descriptor cache path, query cache path)

## 3) Command (Must)

```bash
# exact command used (copy/paste)
python tools/run_calibration.py --config <PATH> --print
```

If scheduled / distributed:
- launcher script:
- worker count / GPU mapping:

## 4) Outputs (Must)

- Output root dir:
- Key files:
  - `metrics.json`
  - `matches.jsonl` / `details.jsonl`
  - plots / summary md
- Validation checks performed:
  - (e.g. num_frames == expected, pair set matches expected data_info)

## 5) Outcome Summary (Must)

- Primary metrics:
- Runtime:
- Observations:
- Known issues / follow-ups:

