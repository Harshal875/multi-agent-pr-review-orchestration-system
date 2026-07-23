"""The POST /webhooks/github endpoint: verify signature, check delivery_id for
idempotency, insert a pending pr_review_records row, enqueue to Redis/ARQ, return 200
immediately. Built in Phase 3."""
