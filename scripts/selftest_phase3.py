"""In-process Phase 3 verification against the LIVE Tiger DB (no Redis/ngrok needed).

Proves the ingress logic end-to-end: HMAC signature check, delivery_id idempotency,
the pending-row write, and the JSON response shape. The ARQ pool is replaced by a fake
that records enqueue calls, so this runs without Redis. Cleans up its own test rows.

Run: python scripts/selftest_phase3.py
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import uuid
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings          # noqa: E402
from backend.main import app                 # noqa: E402


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    async def enqueue_job(self, name: str, *args):
        self.jobs.append((name, args))
        return None


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()


def sync_db_url() -> str:
    # psycopg (sync) understands the libpq URL as-is.
    return settings.tiger_database_url


async def main() -> int:
    fake = FakeArq()
    app.state.arq = fake

    delivery = str(uuid.uuid4())
    payload = {
        "action": "opened",
        "repository": {"full_name": "Harshal875/selftest-repo"},
        "pull_request": {
            "number": 999,
            "title": "Phase 3 selftest PR",
            "draft": False,
            "head": {"sha": "deadbeefcafe"},
        },
    }
    body = json.dumps(payload).encode()

    transport = httpx.ASGITransport(app=app)
    ok = True
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # --- bad signature -> 401
        r = await client.post(
            "/webhooks/github", content=body,
            headers={"X-GitHub-Event": "pull_request",
                     "X-GitHub-Delivery": delivery,
                     "X-Hub-Signature-256": "sha256=deadbeef"},
        )
        print(f"[bad-sig]     status={r.status_code} (expect 401)")
        ok &= r.status_code == 401

        # --- ping -> pong
        r = await client.post(
            "/webhooks/github", content=b"{}",
            headers={"X-GitHub-Event": "ping",
                     "X-GitHub-Delivery": str(uuid.uuid4()),
                     "X-Hub-Signature-256": sign(b"{}")},
        )
        print(f"[ping]        status={r.status_code} body={r.json()} (expect pong)")
        ok &= r.status_code == 200 and r.json().get("pong") is True

        # --- first delivery -> created
        r1 = await client.post(
            "/webhooks/github", content=body,
            headers={"X-GitHub-Event": "pull_request",
                     "X-GitHub-Delivery": delivery,
                     "X-Hub-Signature-256": sign(body)},
        )
        j1 = r1.json()
        print(f"[first]       status={r1.status_code} body={j1} (expect duplicate=false, pending)")
        ok &= r1.status_code == 200 and j1["duplicate"] is False and j1["status"] == "pending"
        review_id = j1["review_id"]

        # --- replay same delivery -> duplicate, same id, NO re-enqueue
        r2 = await client.post(
            "/webhooks/github", content=body,
            headers={"X-GitHub-Event": "pull_request",
                     "X-GitHub-Delivery": delivery,
                     "X-Hub-Signature-256": sign(body)},
        )
        j2 = r2.json()
        print(f"[replay]      status={r2.status_code} body={j2} (expect duplicate=true, same id)")
        ok &= r2.status_code == 200 and j2["duplicate"] is True and j2["review_id"] == review_id

        # --- read endpoint reflects the row
        r3 = await client.get(f"/reviews/{review_id}")
        print(f"[GET review]  status={r3.status_code} status_field={r3.json().get('status')}")
        ok &= r3.status_code == 200 and r3.json()["status"] == "pending"

    print(f"[enqueue]     fake queue jobs={fake.jobs} (expect exactly ONE review_job)")
    ok &= len(fake.jobs) == 1 and fake.jobs[0][0] == "review_job"

    # --- verify exactly one DB row for this delivery, then clean up
    with psycopg.connect(sync_db_url(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pr_review_records WHERE delivery_id=%s", (delivery,))
        n = cur.fetchone()[0]
        print(f"[db]          rows for delivery={n} (expect exactly 1)")
        ok &= n == 1
        cur.execute("DELETE FROM pr_review_records WHERE delivery_id=%s", (delivery,))
        print(f"[cleanup]     deleted {cur.rowcount} test row(s)")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
