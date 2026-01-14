import json
import hashlib
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .config import LLMConfig, load_llm_config


class LLMError(RuntimeError):
    pass


def _sha256_json(obj: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _cache_dir() -> str:
    base = os.environ.get("LITFUSION_CACHE_DIR") or "outputs/lit_fusion_demo/.cache"
    return os.path.join(base, "llm")


def _read_cache(key: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(_cache_dir(), key + ".json")
    if not os.path.exists(path):
        return None
    try:
        return json.loads(open(path, "r").read())
    except Exception:
        return None


def _write_cache(key: str, data: Dict[str, Any]) -> None:
    try:
        d = _cache_dir()
        os.makedirs(d, exist_ok=True)  # py3.2+
        path = os.path.join(d, key + ".json")
        with open(path, "w") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        pass


def _strip_think(text: str) -> str:
    """
    Some local models (e.g., DeepSeek-R1 in Ollama) emit <think>...</think>.
    Strip it to avoid leaking chain-of-thought and to make JSON parsing robust.
    """

    if not isinstance(text, str):
        return ""
    # Remove <think> blocks (non-greedy, multiline)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.strip()


def _cleanup_json_text(text: str) -> str:
    """
    Best-effort cleanup for JSON-ish strings produced by LLMs.
    Keep it conservative: remove obvious wrappers and trailing commas.
    """

    if not isinstance(text, str):
        return ""

    s = text.strip()
    # Remove common Markdown wrappers
    if s.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.*?)```", s, flags=re.S | re.I)
        if m:
            s = (m.group(1) or "").strip()

    s = s.strip().strip("`").strip()

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Common python-ish literals
    s = re.sub(r"\bNone\b", "null", s)
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)

    return s.strip()


def _normalize_base(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    parsed = urlparse(base_url)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1") or path == "/v1":
        return base_url
    return base_url + "/v1"


def _extract_output_text(data: Dict[str, Any]) -> str:
    # Relay/provider variations:
    # - OpenAI Responses: {output:[{type:'message',content:[{type:'output_text',text:'...'}]}]}
    # - Some relays add a convenience 'output_text'
    if isinstance(data.get("output_text"), str) and data.get("output_text").strip():
        return data["output_text"].strip()

    texts = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") in ("output_text", "text"):
                t = c.get("text")
                if isinstance(t, str) and t:
                    texts.append(t)
    if texts:
        return "\n".join(texts).strip()

    # Chat Completions: {choices:[{message:{content:'...'}}]}
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()

    raise LLMError("Could not extract model output from response.")


def _best_effort_json(text: str) -> Any:
    if not isinstance(text, str):
        raise ValueError("Expected a JSON string output.")

    text = _strip_think(text)
    cleaned = _cleanup_json_text(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Try to locate the first JSON object/array in the output.
    start_candidates = [cleaned.find("{"), cleaned.find("[")]
    start_candidates = [i for i in start_candidates if i != -1]
    if not start_candidates:
        raise ValueError("No JSON object/array found in LLM output.")
    start = min(start_candidates)
    end_obj = cleaned.rfind("}")
    end_arr = cleaned.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        raise ValueError("Truncated JSON in LLM output.")
    snippet = _cleanup_json_text(cleaned[start : end + 1])
    return json.loads(snippet)


def _default_for_schema(schema: Optional[Dict[str, Any]]) -> Any:
    t = (schema or {}).get("type")
    if t == "object":
        return {}
    if t == "array":
        return []
    if t == "string":
        return ""
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return None


def _coerce_to_schema(value: Any, schema: Optional[Dict[str, Any]]) -> Any:
    """
    Lightweight coercion to reduce schema-mismatch breakages without bringing jsonschema.
    Only handles the patterns used by this demo.
    """

    schema = schema or {}
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            value = {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        # Ensure required keys exist
        for k in required:
            if k not in value:
                value[k] = _default_for_schema(props.get(k) if isinstance(props, dict) else None)
        # Coerce known properties
        if isinstance(props, dict):
            for k, sub in props.items():
                if k not in value:
                    continue
                value[k] = _coerce_to_schema(value.get(k), sub if isinstance(sub, dict) else None)
        return value

    if t == "array":
        if value is None:
            value = []
        if isinstance(value, str):
            # Split on newlines/commas for common LLM mistakes
            parts = [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]
            value = parts
        if not isinstance(value, list):
            value = [value]
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            value = [_coerce_to_schema(v, items_schema) for v in value]
        return value

    if t == "string":
        if value is None:
            return ""
        if not isinstance(value, str):
            return str(value)
        return value

    if t == "integer":
        try:
            return int(value)
        except Exception:
            return 0

    if t == "number":
        try:
            return float(value)
        except Exception:
            return 0.0

    if t == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y")
        return bool(value)

    return value


class LLMClient:
    def __init__(
        self,
        cfg: Optional[LLMConfig] = None,
        timeout_s: int = 120,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        provider:
          - openai: OpenAI-compatible /v1 endpoints (default)
          - ollama: local Ollama (http://localhost:11434)
          - auto: try openai then fall back to ollama on auth/quota errors
        """

        self.timeout_s = timeout_s
        self.provider = (provider or os.environ.get("LITFUSION_PROVIDER") or "auto").strip().lower()
        if self.provider not in ("openai", "ollama", "auto"):
            raise ValueError("LITFUSION_PROVIDER must be openai/ollama/auto")

        self.ollama_base = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip().rstrip("/")
        self.ollama_model = (model or os.environ.get("OLLAMA_MODEL") or "deepseek-r1:7b").strip()

        self.cfg = None  # type: Optional[LLMConfig]
        self.base = None  # type: Optional[str]
        self.openai_model = None  # type: Optional[str]

        if self.provider == "ollama":
            return

        try:
            self.cfg = cfg or load_llm_config()
            self.base = _normalize_base(self.cfg.base_url)
            self.openai_model = self.cfg.model
        except Exception as e:
            if self.provider == "auto":
                # No OpenAI config -> use Ollama.
                self.provider = "ollama"
                return
            raise

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer %s" % self.cfg.api_key,
            "Content-Type": "application/json",
        }

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_s)
        if r.status_code >= 400:
            raise LLMError("LLM HTTP %s: %s" % (r.status_code, r.text[:4000]))
        try:
            return r.json()
        except Exception as e:
            raise LLMError("Invalid JSON from LLM: %s" % e)

    def _ollama_chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_output_tokens: Optional[int],
        json_mode: bool = False,
    ) -> str:
        url = self.ollama_base + "/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": float(temperature)},
        }
        if json_mode:
            # Ollama supports a JSON grammar mode that forces valid JSON output.
            payload["format"] = "json"
        # Ollama uses num_predict for generation length.
        if max_output_tokens is not None:
            payload["options"]["num_predict"] = int(max_output_tokens)
        r = requests.post(url, json=payload, timeout=self.timeout_s)
        if r.status_code >= 400:
            raise LLMError("Ollama HTTP %s: %s" % (r.status_code, r.text[:2000]))
        data = r.json()
        msg = (data.get("message") or {}).get("content")
        if not isinstance(msg, str):
            raise LLMError("Invalid Ollama response.")
        return _strip_think(msg)

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = 1200,
    ) -> str:
        cache_key = _sha256_json(
            {
                "kind": "text",
                "provider": self.provider,
                "openai_model": self.openai_model,
                "ollama_model": self.ollama_model,
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            }
        )
        cached = _read_cache(cache_key)
        if cached and isinstance(cached.get("output_text"), str):
            return cached["output_text"]

        if self.provider == "ollama":
            out = self._ollama_chat(system=system, user=user, temperature=temperature, max_output_tokens=max_output_tokens)
            _write_cache(cache_key, {"output_text": out})
            return out

        # Prefer Responses API; fallback to Chat Completions.
        responses_url = self.base + "/responses"
        chat_url = self.base + "/chat/completions"

        payload = {
            "model": self.openai_model,
            "instructions": system,
            "input": user,
            "temperature": temperature,
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens

        try:
            data = self._post_json(responses_url, payload)
            out = _extract_output_text(data)
            _write_cache(cache_key, {"output_text": out})
            return out
        except Exception as e:
            # Auto fallback to Ollama on auth/quota errors.
            if self.provider == "auto" and "HTTP 401" in str(e):
                out = self._ollama_chat(system=system, user=user, temperature=temperature, max_output_tokens=max_output_tokens)
                _write_cache(cache_key, {"output_text": out, "fallback": "ollama"})
                return out
            data = self._post_json(
                chat_url,
                {
                    "model": self.openai_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,
                },
            )
            out = _extract_output_text(data)
            _write_cache(cache_key, {"output_text": out})
            return out

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        json_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = 1600,
        retries: int = 2,
    ) -> Any:
        cache_key = _sha256_json(
            {
                "kind": "json",
                "provider": self.provider,
                "openai_model": self.openai_model,
                "ollama_model": self.ollama_model,
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "schema": json_schema or {},
            }
        )
        cached = _read_cache(cache_key)
        if cached and "output_json" in cached:
            return cached["output_json"]

        if self.provider == "ollama":
            last_err = None
            for attempt in range(retries + 1):
                try:
                    hint = ""
                    if json_schema:
                        # Keep schema compact to avoid huge prompts.
                        hint = "\n\nJSON schema (reference):\n" + json.dumps(
                            json_schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        )
                    txt = self._ollama_chat(
                        system=system,
                        user=user + hint,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        json_mode=True,
                    )
                    out = _best_effort_json(txt)
                    if json_schema:
                        out = _coerce_to_schema(out, json_schema)
                    _write_cache(cache_key, {"output_json": out})
                    return out
                except Exception as e:
                    last_err = e
                    # Retry with stricter instruction and lower temperature.
                    temperature = 0.0
                    user = user + "\n\nSTRICT: Output ONLY JSON. No markdown, no code fences, no comments."
                    time.sleep(0.6 * (attempt + 1))
            raise LLMError("Failed to get valid JSON from Ollama: %s" % last_err)

        # Try structured JSON mode when available; otherwise prompt+parse.
        responses_url = self.base + "/responses"
        chat_url = self.base + "/chat/completions"

        last_err = None
        for attempt in range(retries + 1):
            try:
                payload = {
                    "model": self.openai_model,
                    "instructions": system,
                    "input": user,
                    "temperature": temperature,
                }
                if max_output_tokens is not None:
                    payload["max_output_tokens"] = max_output_tokens
                if json_schema:
                    payload["text"] = {
                        "format": {
                            "type": "json_schema",
                            "json_schema": {"name": "litfusion", "schema": json_schema, "strict": True},
                        }
                    }
                else:
                    payload["text"] = {"format": {"type": "json_object"}}

                data = self._post_json(responses_url, payload)
                out = _best_effort_json(_extract_output_text(data))
                _write_cache(cache_key, {"output_json": out})
                return out
            except Exception as e:
                last_err = e
                if self.provider == "auto" and "HTTP 401" in str(e):
                    try:
                        txt = self._ollama_chat(
                            system=system,
                            user=user + "\n\nReturn ONLY valid JSON.",
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                            json_mode=True,
                        )
                        out = _best_effort_json(txt)
                        if json_schema:
                            out = _coerce_to_schema(out, json_schema)
                        _write_cache(cache_key, {"output_json": out, "fallback": "ollama"})
                        return out
                    except Exception as e2:
                        last_err = e2

            # Fallback to chat completions.
            try:
                payload = {
                    "model": self.openai_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,
                }
                # Some providers support response_format, some don't; keep prompt as primary contract.
                data = self._post_json(chat_url, payload)
                out = _best_effort_json(_extract_output_text(data))
                _write_cache(cache_key, {"output_json": out})
                return out
            except Exception as e:
                last_err = e
                if self.provider == "auto" and "HTTP 401" in str(e):
                    try:
                        txt = self._ollama_chat(
                            system=system,
                            user=user + "\n\nReturn ONLY valid JSON.",
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                            json_mode=True,
                        )
                        out = _best_effort_json(txt)
                        if json_schema:
                            out = _coerce_to_schema(out, json_schema)
                        _write_cache(cache_key, {"output_json": out, "fallback": "ollama"})
                        return out
                    except Exception as e2:
                        last_err = e2

            time.sleep(0.8 * (attempt + 1))

        raise LLMError("Failed to get valid JSON from LLM: %s" % last_err)

    def embed_texts(self, texts, model: Optional[str] = None):
        """
        Call embeddings endpoint.
        Returns: List[List[float]]
        """

        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts:
            return []

        if self.provider == "ollama":
            embed_model = (model or os.environ.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip()
            url = self.ollama_base + "/api/embeddings"
            embs = []
            for t in texts:
                r = requests.post(url, json={"model": embed_model, "prompt": t}, timeout=self.timeout_s)
                if r.status_code >= 400:
                    raise LLMError("Ollama embeddings HTTP %s: %s" % (r.status_code, r.text[:2000]))
                data = r.json()
                e = data.get("embedding")
                if not isinstance(e, list) or not e:
                    raise LLMError("Invalid Ollama embeddings response.")
                embs.append(e)
            return embs

        embed_model = model or os.environ.get("OPENAI_EMBED_MODEL") or "text-embedding-3-small"
        url = self.base + "/embeddings"
        try:
            data = self._post_json(url, {"model": embed_model, "input": texts})
        except Exception as e:
            if self.provider == "auto" and "HTTP 401" in str(e):
                # Fall back to Ollama embeddings if available.
                embed_model2 = (os.environ.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip()
                url2 = self.ollama_base + "/api/embeddings"
                embs = []
                for t in texts:
                    r = requests.post(url2, json={"model": embed_model2, "prompt": t}, timeout=self.timeout_s)
                    if r.status_code >= 400:
                        raise LLMError("Ollama embeddings HTTP %s: %s" % (r.status_code, r.text[:2000]))
                    data2 = r.json()
                    e2 = data2.get("embedding")
                    if not isinstance(e2, list) or not e2:
                        raise LLMError("Invalid Ollama embeddings response.")
                    embs.append(e2)
                return embs
            raise

        items = data.get("data") or []
        if not isinstance(items, list):
            raise LLMError("Invalid embeddings response.")

        # Ensure order by index when present
        try:
            items = sorted(items, key=lambda x: int((x or {}).get("index", 0)))
        except Exception:
            pass

        embs = []
        for it in items:
            if not isinstance(it, dict):
                continue
            e = it.get("embedding")
            if isinstance(e, list) and e:
                embs.append(e)

        if len(embs) != len(texts):
            raise LLMError("Embeddings count mismatch: got %d expected %d" % (len(embs), len(texts)))

        return embs
