"""Send a correctly-signed pull_request webhook to a RUNNING server.

Use this to exercise the full live stack (uvicorn + real Redis enqueue) without opening
a GitHub PR. Sends the same delivery twice to demonstrate idempotency.

Run (server on localhost:8000):
    python scripts/send_test_webhook.py
    python scripts/send_test_webhook.py http://localhost:8000
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import settings  # noqa: E402


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    delivery = str(uuid.uuid4())
    payload = {
        "action": "opened",
        "repository": {"full_name": "Harshal875/live-test-repo"},
        "pull_request": {
            "number": 1,
            "title": "Live webhook test",
            "draft": False,
            "head": {"sha": uuid.uuid4().hex},
        },
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": sign(body),
    }

    with httpx.Client(base_url=base, timeout=10) as client:
        r1 = client.post("/webhooks/github", content=body, headers=headers)
        print("first :", r1.status_code, r1.json())
        r2 = client.post("/webhooks/github", content=body, headers=headers)
        print("replay:", r2.status_code, r2.json())
        q = client.get("/queue/status")
        print("queue :", q.status_code, q.json())

    print(f"\ndelivery_id used: {delivery}")


if __name__ == "__main__":
    main()
