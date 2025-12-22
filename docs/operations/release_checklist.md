# Public Release Checklist

This checklist is intended to keep the public repository **reproducible and coherent** (especially for Table III GT sweeps), while clearly separating “core method” vs. “work-in-progress” extensions.

## Must-have (public)

1. **Core pipeline runs on DAIR-V2X GT**
   - `python tools/run_dair_pipeline_experiments.py --config configs/pipeline_top3000.yaml`
   - Verify outputs are produced under `outputs/<tag>/metrics.json` and `outputs/<tag>/matches.jsonl`.

2. **Docs point to the right entrypoints**
   - Public entry: `docs/operations/experiment_progress_public.md`
   - Full reproduction guide: `docs/operations/experiment_reproduction.md`
   - Internal logs (optional): `docs/operations/experiment_progress_internal.md` (do not cite as paper numbers)

3. **No machine-specific paths**
   - Avoid hard-coded `/mnt/...`, `/data2/...` paths in public-facing docs/config examples.
   - Prefer “symlink into `data/DAIR-V2X/`” instructions.

4. **Submodules instructions**
   - `git submodule update --init --recursive` is documented for baseline scripts under `benchmarks/`.

## Optional (public, clearly marked as WIP)

- Detection-cache runs (`data.use_detection=true`) and HEAL integration:
  - Keep the adapter/tools and configs, but avoid publishing exploratory metrics as “paper reproduction”.
  - Recommend users provide their own detection caches; caches are ignored by git.

- Classical/global registration baselines:
  - Keep scripts under `benchmarks/`, but call out heavy dependencies (TEASER++ python bindings, Open3D, etc.).

