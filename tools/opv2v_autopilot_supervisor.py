#!/usr/bin/env python3
"""
Async supervisor for OPV2V autopilot.

Behavior:
- Launch autopilot in rounds (attempts) with unique tags.
- Detect abnormal exits and persist an incident report with log evidence.
- Optionally run a failure hook (for notifications or external Codex wake-up).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY39 = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(path, msg):
    line = "[{}] {}\n".format(_now(), msg)
    print(line, end="", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _tail(path, n=80):
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-n:])


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_markdown(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args():
    # Support forwarding autopilot args after '--'
    argv = sys.argv[1:]
    if "--" in argv:
        split = argv.index("--")
        sup_argv = argv[:split]
        autopilot_argv = argv[split + 1 :]
    else:
        sup_argv = argv
        autopilot_argv = []

    ap = argparse.ArgumentParser(description="Supervisor for tools/opv2v_benchmark_autopilot.py")
    ap.add_argument("--tag", type=str, default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--python-bin", type=Path, default=PY39)
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--retry-wait-seconds", type=int, default=20)
    ap.add_argument(
        "--failure-hook",
        type=str,
        default="",
        help="Shell command run on abnormal exit. Supports placeholders: {incident},{tag},{attempt},{rc},{root}.",
    )
    ap.add_argument(
        "--stop-after-hook-failure",
        action="store_true",
        help="If failure hook exits non-zero, stop immediately.",
    )
    args = ap.parse_args(sup_argv)
    return args, autopilot_argv


def _attempt_tag(base_tag, attempt):
    if attempt <= 1:
        return base_tag
    return "{}_r{}".format(base_tag, attempt)


def _launch_autopilot(args, attempt_tag, autopilot_argv, log_path):
    out_dir = ROOT / "outputs" / ("opv2v_autopilot_" + attempt_tag)
    out_dir.mkdir(parents=True, exist_ok=True)
    launcher_log = out_dir / "launcher.log"
    autopilot_log = out_dir / "autopilot.log"
    cmd = [str(args.python_bin), str(ROOT / "tools" / "opv2v_benchmark_autopilot.py"), "--tag", attempt_tag]
    cmd.extend(autopilot_argv)
    _log(log_path, "launch attempt_tag={} cmd={}".format(attempt_tag, " ".join(cmd)))
    lf = launcher_log.open("a", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)
    return proc, lf, out_dir, launcher_log, autopilot_log, cmd


def _monitor_attempt(proc, poll_seconds, autopilot_log, log_path):
    last_line = None
    heartbeat_every = max(5, int(poll_seconds))
    last_heartbeat_ts = 0.0
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc
        now = time.time()
        if now - last_heartbeat_ts >= heartbeat_every:
            tail = _tail(autopilot_log, n=1).strip()
            if tail and tail != last_line:
                _log(log_path, "heartbeat {}".format(tail))
                last_line = tail
            last_heartbeat_ts = now
        time.sleep(2)


def _run_failure_hook(args, hook_cmd, *, incident_path, tag, attempt, rc, log_path):
    if not hook_cmd:
        return 0
    cmd = hook_cmd.format(
        incident=str(incident_path),
        tag=str(tag),
        attempt=str(int(attempt)),
        rc=str(int(rc)),
        root=str(ROOT),
    )
    _log(log_path, "run failure hook: {}".format(cmd))
    proc = subprocess.run(cmd, shell=True, cwd=str(ROOT))
    _log(log_path, "failure hook rc={}".format(proc.returncode))
    return int(proc.returncode)


def _write_incident(supervisor_dir, *, base_tag, attempt, attempt_tag, rc, cmd, autopilot_log, launcher_log):
    incident = supervisor_dir / "incidents" / "incident_attempt{:02d}.md".format(int(attempt))
    lines = []
    lines.append("# OPV2V Autopilot Incident")
    lines.append("")
    lines.append("- generated_at: {}".format(_now()))
    lines.append("- base_tag: {}".format(base_tag))
    lines.append("- attempt: {}".format(int(attempt)))
    lines.append("- attempt_tag: {}".format(attempt_tag))
    lines.append("- exit_code: {}".format(int(rc)))
    lines.append("- command: `{}`".format(" ".join(cmd)))
    lines.append("- autopilot_log: `{}`".format(autopilot_log))
    lines.append("- launcher_log: `{}`".format(launcher_log))
    lines.append("")
    lines.append("## autopilot.log tail")
    lines.append("```text")
    lines.append(_tail(autopilot_log, n=120))
    lines.append("```")
    lines.append("")
    lines.append("## launcher.log tail")
    lines.append("```text")
    lines.append(_tail(launcher_log, n=120))
    lines.append("```")
    _write_markdown(incident, lines)
    return incident


def _write_report(path, payload):
    lines = ["# OPV2V Autopilot Supervisor Report", ""]
    for k in sorted(payload.keys()):
        lines.append("- {}: {}".format(k, payload[k]))
    lines.append("")
    _write_markdown(path, lines)


def main():
    args, autopilot_argv = _parse_args()
    base_tag = args.tag
    supervisor_dir = ROOT / "outputs" / ("opv2v_autopilot_supervisor_" + base_tag)
    supervisor_dir.mkdir(parents=True, exist_ok=True)
    log_path = supervisor_dir / "supervisor.log"
    state_path = supervisor_dir / "state.json"
    report_path = ROOT / "docs" / "operations" / ("opv2v_autopilot_supervisor_report_" + base_tag + ".md")

    _log(log_path, "supervisor start tag={} max_attempts={}".format(base_tag, int(args.max_attempts)))
    if autopilot_argv:
        _log(log_path, "forward autopilot args: {}".format(" ".join(autopilot_argv)))

    incidents = []
    final = {
        "tag": base_tag,
        "status": "running",
        "supervisor_dir": supervisor_dir,
        "supervisor_log": log_path,
        "max_attempts": int(args.max_attempts),
    }
    _write_json(state_path, final)

    for attempt in range(1, int(args.max_attempts) + 1):
        attempt_tag = _attempt_tag(base_tag, attempt)
        proc, lf, out_dir, launcher_log, autopilot_log, cmd = _launch_autopilot(args, attempt_tag, autopilot_argv, log_path)
        _write_json(
            state_path,
            {
                "status": "running",
                "tag": base_tag,
                "attempt": attempt,
                "attempt_tag": attempt_tag,
                "pid": int(proc.pid),
                "autopilot_dir": str(out_dir),
                "autopilot_log": str(autopilot_log),
                "launcher_log": str(launcher_log),
                "time": _now(),
            },
        )

        rc = _monitor_attempt(proc, args.poll_seconds, autopilot_log, log_path)
        lf.close()
        if int(rc) == 0:
            final.update(
                {
                    "status": "success",
                    "attempt": attempt,
                    "attempt_tag": attempt_tag,
                    "final_autopilot_dir": out_dir,
                    "final_autopilot_log": autopilot_log,
                    "incidents": len(incidents),
                }
            )
            _write_json(state_path, final)
            _write_report(report_path, final)
            _log(log_path, "supervisor success attempt={} tag={}".format(attempt, attempt_tag))
            return

        _log(log_path, "abnormal exit attempt={} tag={} rc={}".format(attempt, attempt_tag, int(rc)))
        incident = _write_incident(
            supervisor_dir,
            base_tag=base_tag,
            attempt=attempt,
            attempt_tag=attempt_tag,
            rc=rc,
            cmd=cmd,
            autopilot_log=autopilot_log,
            launcher_log=launcher_log,
        )
        incidents.append(str(incident))

        hook_rc = _run_failure_hook(
            args,
            args.failure_hook,
            incident_path=incident,
            tag=base_tag,
            attempt=attempt,
            rc=rc,
            log_path=log_path,
        )
        if hook_rc != 0 and args.stop_after_hook_failure:
            final.update(
                {
                    "status": "failed",
                    "error": "failure hook returned non-zero",
                    "attempt": attempt,
                    "attempt_tag": attempt_tag,
                    "hook_rc": hook_rc,
                    "incidents": incidents,
                }
            )
            _write_json(state_path, final)
            _write_report(report_path, final)
            raise SystemExit(2)

        if attempt < int(args.max_attempts):
            _log(log_path, "sleep {}s before retry".format(int(args.retry_wait_seconds)))
            time.sleep(max(1, int(args.retry_wait_seconds)))

    final.update(
        {
            "status": "failed",
            "error": "max attempts exhausted",
            "incidents": incidents,
        }
    )
    _write_json(state_path, final)
    _write_report(report_path, final)
    _log(log_path, "supervisor failed: max attempts exhausted")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
