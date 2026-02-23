# Repo Hygiene & Git Workflow (Main + Submodules)

This repo is a **multi-repo worktree**:
- the main repo (`v2xreg_private`),
- plus submodules (notably `HEAL/` and several `third_party/*`).

The goal of this document is to make “save a run” boring and reproducible.

## 1) Golden Rules

1) **Never “commit submodule changes” from the main repo.**
   - If you edit files under `HEAL/`, you must commit them **inside** the HEAL repo.
   - The main repo only records a *pointer* to a HEAL commit.

2) **Do not version big artifacts.**
   - `outputs/`, dataset copies, and reference PDFs are not part of git history.
   - Reference PDFs: see `docs/REFERENCES.md`.

3) **One run = one provenance record.**
   - For any full/canonical run, create a short run note using
     `docs/operations/run_template.md`.

## 2) Recommended “Save Snapshot” Flow

In the main repo:
```bash
git checkout -b snapshot/YYYY-MM-DD-topic
```

If `HEAL/` is dirty:
```bash
git -C HEAL checkout -b snapshot/YYYY-MM-DD-topic
git -C HEAL status -sb
git -C HEAL add -p
git -C HEAL commit -m 'feat/fix/docs/chore: ...'
git -C HEAL push -u origin snapshot/YYYY-MM-DD-topic
```

Back to the main repo:
```bash
git status -sb
git add -p
git add HEAL  # record the updated submodule pointer (only after HEAL commit)
git commit -m 'chore: bump HEAL submodule'
git push -u origin snapshot/YYYY-MM-DD-topic
```

## 3) Commit Message Style (Local Convention)

Use lightweight prefixes that match existing history:
- `docs: ...`
- `exp: ...`
- `hkust: ...`
- `feat: ...`
- `fix: ...`
- `chore: ...`

Prefer small commits over “mega commits”. If a commit mixes unrelated changes,
split it.

## 4) Preflight Checks (Before You Push)

Run the preflight script (added in this repo) to catch common hygiene mistakes:
```bash
scripts/preflight_save.sh
```

Typical failures it should prevent:
- accidentally tracking PDFs or datasets,
- weird temporary files in repo root,
- dirty submodules left uncommitted,
- large untracked files you forgot to document.

## 5) Benchmark Provenance (Non-Negotiable for Canonical Numbers)

For any OPV2V/DAIR run that you intend to cite as “latest / canonical”, make sure the run directory
contains a `config_snapshot.json` with:
- `git_commit`, `git_branch`, `git_dirty`
- `heal_commit`, `heal_branch`, `heal_dirty`

Rule of thumb:
- `git_dirty=true` => treat the run as **debug/provisional**, not a fair benchmark line.
