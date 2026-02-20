# Repo Transfer / Upload Checklist

Last updated: 2026-02-11

This note records how to move the project to another server while keeping the
code state reproducible and the transfer size reasonable.

## Option A — Tarball (fastest, includes untracked files)

On the source machine:

```bash
./scripts/pack_repo_for_transfer.sh
```

This creates a tarball under `exports/` with large folders excluded:
`data/`, `outputs/`, `logs/`, `HEAL/opencood/logs/`, `HEAL/dataset/`, `HEAL/data/`,
and local env caches.

Transfer + extract on the target:

```bash
tar -xzf exports/v2xreg_private_src_<STAMP>.tar.gz -C /path/to/target
```

Because `.git` is excluded, the tarball contains the full working tree
including the HEAL submodule contents and any untracked files.

## Option B — Git + patches (clean history)

On the source machine:

```bash
./scripts/export_local_patches.sh
```

This writes a patch bundle under `exports/patches_<STAMP>/`:

- `main.diff` / `heal.diff`: uncommitted diffs
- `*_untracked.txt`: list of untracked files to copy

On the target machine:

```bash
git clone <your_repo_url>
cd v2xreg_private
git submodule update --init --recursive

# Apply patches
git apply /path/to/patches_<STAMP>/main.diff
git -C HEAL apply /path/to/patches_<STAMP>/heal.diff
```

Then copy the untracked files listed in `main_untracked.txt` and
`heal_untracked.txt` if you need them.

## After transfer (datasets + caches)

```bash
OPV2V_ROOT=/data/OPV2V ./scripts/prepare_opv2v_dataset.sh
./scripts/build_opv2v_stage1_cache.sh
```

`scripts/run_opv2v_fullbench.sh` can then launch the full benchmark.

## Notes

- `PYTHON_BIN` can be set to point to your Python executable; scripts auto‑detect
  `.micromamba/envs/py39/bin/python` or fall back to `python3`/`python`.
- If you use the tarball option, you do not need to run `git submodule update`.
