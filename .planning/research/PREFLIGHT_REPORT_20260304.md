# Preflight Report (2026-03-04)

## 结论

BLOCK (for full-scale three-dataset benchmark launch)

## P0 阻塞项

1. **Input contract is still not concrete enough for deterministic rerun (G3 FAIL).**
   - Missing explicit model/stage1 path and expected sample checks per dataset in runbook commands.
2. **Mechanism effectiveness checks are not yet wired into run closure (G6 FAIL).**
   - No explicit required outputs for applied-count / reject reasons in closure checklist.
3. **Budget guardrail is not yet quantified (G10 FAIL).**
   - Stop-loss rules exist, but no numeric GPU-hour or wall-clock budget threshold is pinned.

## Gate 表

| Gate | Verdict | Evidence |
|------|---------|----------|
| G0 Goal / Decision | PASS | `.planning/ROADMAP.md:5`, `.planning/ROADMAP.md:120` |
| G1 Definition-of-Done | PASS | Phase success criteria in `.planning/ROADMAP.md:49`, `.planning/ROADMAP.md:64`, `.planning/ROADMAP.md:109` |
| G2 Semantics Freeze | PASS | `.planning/ROADMAP.md:19` to `.planning/ROADMAP.md:25`; command flags in `.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:27`, `:64`, `:101` |
| G3 Input Contract | FAIL | Runbook lacks explicit pinned model/stage1 paths and expected sample assertions (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:22` to `:122`) |
| G4 Checkpoint / Toolchain Health | PASS | Smoke-first commands for all datasets (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:19`, `:52`, `:93`) |
| G5 Confound / Cancellation | PASS | Explicit compare pins and gating across commands (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:10`, `:29`, `:66`, `:103`) |
| G6 Effectiveness (Thing Actually Applies) | FAIL | Requirements ask for failure decomposition but runbook lacks mandatory extraction commands (`.planning/REQUIREMENTS.md:30`, `.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:158`) |
| G7 Source-of-Truth | PASS | SoT section in roadmap (`.planning/ROADMAP.md:27`) and required artifacts list (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:11`) |
| G8 Resume / Re-run Safety | PASS | Timestamped tags/run-id patterns (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:23`, `:56`, `:97`) |
| G9 Smoke-First | PASS | Smoke and full sections are separated per dataset (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:19`, `:35`, `:52`, `:72`, `:93`, `:109`) |
| G10 Cost / Stop-Loss | FAIL | Stop-loss exists but no numeric budget (`.planning/research/BENCHMARK_COMMAND_RUNBOOK.md:158`) |

Additional static lint evidence:
- Command: `python3 /home/qqxluca/.codex/skills/plan-preflight/scripts/plan_lint.py --plan .planning/ROADMAP.md`
- Result: `verdict=PASS score=100` (structure complete, but operational blockers remain)

## 证据链

1. **Fact:** Roadmap and runbook now freeze semantics and SoT artifacts.  
   **Implication:** Comparability and auditability are structurally defined.  
   **Risk:** Without concrete input pinning (paths/count checks), reruns can still drift.

2. **Fact:** Smoke-first sequencing is explicit for DAIR/OPV2V/V2V4Real.  
   **Implication:** Expensive invalid full runs can be filtered early.  
   **Risk:** If smoke success criteria do not include mechanism-effectiveness counters, false positives remain possible.

3. **Fact:** Standards comparison and two-layer recommendation are documented.  
   **Implication:** Cloud standard selection can be decision-driven rather than ad-hoc.  
   **Risk:** Transition bundles with placeholder depth/scale metrics may still block route-decision gates.

## 止损执行单

1. Add explicit `--model-dir` / `--stage1-result` / expected sample contract checks to runbook for each dataset.
2. Add mandatory post-run extraction commands for applied/reject/failure reason stats and require them in closure reports.
3. Add numeric budget guardrails per dataset (max GPU-hours, max rerun count, timeout threshold).
4. Re-run this preflight and require G3/G6/G10 all PASS before any full run launch.

## 复跑验收条件

- `plan_lint` remains PASS for `.planning/ROADMAP.md`.
- Runbook includes explicit pinned input contracts (paths + expected counts) for all three datasets.
- Runbook includes required effectiveness metrics extraction steps and output artifact paths.
- Budget table exists with concrete thresholds and stop conditions.
- Gate table re-evaluation result: all G0-G10 PASS, with no P0 blockers.
