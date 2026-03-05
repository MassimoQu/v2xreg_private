from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_TOKEN_PATH = Path.home() / ".secrets" / "gh_token"
GQL_ENDPOINT = "https://api.github.com/graphql"


def read_gh_token(*, token_path: Path = DEFAULT_TOKEN_PATH) -> str:
    """
    Reads the GitHub token from ~/.secrets/gh_token (by default).

    Important:
      - Do NOT persist the token anywhere else.
      - Do NOT print the token.
    """
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("Empty GitHub token file: {}".format(token_path))
    return token


@dataclass
class GitHubGraphQLClient:
    token: str
    endpoint: str = GQL_ENDPOINT
    user_agent: str = "v2xreg-private-projectv2-sync"

    def execute(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": "bearer {}".format(self.token),
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if "errors" in data:
            raise RuntimeError("GitHub GraphQL errors: {}".format(data["errors"]))
        return data


class ProjectV2Writer:
    """
    Placeholder for future GitHub Projects V2 write support.

    Intended flow:
      - take normalized Items (tools.projectv2_sync.models.Item)
      - upsert/update into a target ProjectV2 via GraphQL mutations
      - store uid<->project_item_id mapping locally (NOT implemented here)
    """

    def __init__(self, *, client: GitHubGraphQLClient) -> None:
        self._client = client

    def upsert_items(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Write mode is intentionally not implemented (dry-run only).")

