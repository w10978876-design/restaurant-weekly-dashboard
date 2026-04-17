from __future__ import annotations

import base64
import json
from typing import Any

import requests


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_file_content(
    *,
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str,
) -> tuple[str | None, str | None]:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}
    r = requests.get(url, headers=_headers(token), params=params, timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return None, None
    content_b64 = data.get("content")
    sha = data.get("sha")
    if not content_b64:
        return None, sha
    content = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8")
    return content, sha


def put_file_content(
    *,
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    content_text: str,
    sha: str | None,
) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content_text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=_headers(token), data=json.dumps(body), timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub API error {r.status_code}: {r.text}")
