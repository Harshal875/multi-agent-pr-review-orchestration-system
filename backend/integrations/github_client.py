"""GitHub REST API wrapper - fetch PR diffs and post reviews, as a GitHub App.

Auth chain (GitHub App, not a personal token): the App's private key signs a short-lived
RS256 JWT (iss = app id); that JWT mints a per-installation access token (valid ~1h,
cached here until near expiry); that installation token authorizes repo calls. This is
what lets the review land as the App's own identity on the PR, not a human's.

Network calls are retry-wrapped (reliability/retry.py) on transport errors. A 4xx
(raise_for_status) fails fast and is NOT retried - a 404/422 won't succeed on retry.
Callers (the worker, the HITL approve path) treat a raised error as "posting failed,
don't mark posted" rather than crashing the review."""

from __future__ import annotations

import time

import httpx
import jwt

from backend.config import settings
from backend.reliability.retry import with_retry

_API = "https://api.github.com"
_RETRYABLE = (httpx.TransportError,)  # connect/read/timeout - network, not 4xx


class GitHubClient:
    def __init__(self) -> None:
        self._private_key: str | None = None
        # repo full_name -> (installation_token, expires_at_epoch)
        self._token_cache: dict[str, tuple[str, float]] = {}

    def _key(self) -> str:
        if self._private_key is None:
            with open(settings.github_private_key_path, encoding="utf-8") as f:
                self._private_key = f.read()
        return self._private_key

    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}
        return jwt.encode(payload, self._key(), algorithm="RS256")

    @staticmethod
    def _app_headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @with_retry(max_attempts=3, base_delay_s=0.5, retry_on=_RETRYABLE)
    async def _get(self, url: str, headers: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp

    @with_retry(max_attempts=3, base_delay_s=0.5, retry_on=_RETRYABLE)
    async def _post(self, url: str, headers: dict, json: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=json)
        resp.raise_for_status()
        return resp

    async def _installation_token(self, repo: str) -> str:
        cached = self._token_cache.get(repo)
        if cached and cached[1] - time.time() > 60:  # still valid for >1 min
            return cached[0]

        jwt_headers = self._app_headers(self._app_jwt())
        # Find the installation that covers this repo, then mint its token.
        inst = await self._get(f"{_API}/repos/{repo}/installation", jwt_headers)
        installation_id = inst.json()["id"]
        tok = await self._post(
            f"{_API}/app/installations/{installation_id}/access_tokens", jwt_headers, {}
        )
        data = tok.json()
        # expires_at is ISO 8601; parse to epoch for the cache.
        expires = time.mktime(time.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))
        self._token_cache[repo] = (data["token"], expires)
        return data["token"]

    async def fetch_pr_diff(self, repo: str, pr_number: int) -> str:
        """Return the unified diff for a PR (as the raw text the specialists review)."""
        token = await self._installation_token(repo)
        headers = self._app_headers(token) | {"Accept": "application/vnd.github.diff"}
        resp = await self._get(f"{_API}/repos/{repo}/pulls/{pr_number}", headers)
        return resp.text

    async def post_review(
        self, repo: str, pr_number: int, body: str, event: str = "COMMENT"
    ) -> str:
        """Post a review to a PR. event: COMMENT | REQUEST_CHANGES | APPROVE. Returns the
        GitHub review id (stored on pr_review_records.github_review_id)."""
        token = await self._installation_token(repo)
        resp = await self._post(
            f"{_API}/repos/{repo}/pulls/{pr_number}/reviews",
            self._app_headers(token),
            {"body": body, "event": event},
        )
        return str(resp.json()["id"])


_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client
