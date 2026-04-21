import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple


class LLMConfig(object):
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model


def _read_codex_config_toml(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Minimal parser for ~/.codex/config.toml.

    We only need:
      - top-level: model = "..."
      - [model_providers.codex]: base_url = "..."
    """

    if not path.exists():
        return None, None

    current_section = None
    model = None
    base_url = None

    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue

        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*(.+)\s*$', line)
        if not m:
            continue

        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]

        if current_section is None and key == "model":
            model = val
        if current_section == "model_providers.codex" and key == "base_url":
            base_url = val

    return base_url, model


def _read_codex_auth_json(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    api_key = data.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None


def load_llm_config() -> LLMConfig:
    """
    Resolution order:
      1) env: OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL
      2) ~/.codex/config.toml + ~/.codex/auth.json
    """

    env_base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    env_api_key = os.environ.get("OPENAI_API_KEY")
    env_model = os.environ.get("OPENAI_MODEL")

    base_url = env_base_url
    api_key = env_api_key
    model = env_model

    codex_dir = Path.home() / ".codex"
    if not base_url or not model:
        cfg_base_url, cfg_model = _read_codex_config_toml(codex_dir / "config.toml")
        base_url = base_url or cfg_base_url
        model = model or cfg_model

    if not api_key:
        api_key = _read_codex_auth_json(codex_dir / "auth.json")

    missing = [k for k, v in [("base_url", base_url), ("api_key", api_key), ("model", model)] if not v]
    if missing:
        raise RuntimeError(
            "Missing LLM config: %s. Set env OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL "
            "or configure ~/.codex/{config.toml,auth.json}." % ", ".join(missing)
        )

    return LLMConfig(base_url=base_url, api_key=api_key, model=model)
