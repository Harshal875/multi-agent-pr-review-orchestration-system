"""Phase 6 DoD: hybrid retrieval returns relevant chunks for a real diff.

Query A is a diff touching the billing/Stripe code -> billing/stripe.py must appear in
the top-3. Query B is unrelated -> billing/stripe.py must NOT be the top hit. Also prints
each lane so you can see vector vs keyword contributions. Uses the live sample-repo corpus.

Run: python scripts/phase6_retrieval_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.memory.context_retriever import retrieve            # noqa: E402
from backend.memory.embedder import embed_query                  # noqa: E402
from backend.memory.tiger_client import get_memory_client        # noqa: E402

REPO = "sample-repo"

STRIPE_DIFF = """\
--- a/billing/stripe.py
+++ b/billing/stripe.py
@@ def charge_customer(customer_id, amount_cents):
-    return stripe.Charge.create(customer=customer_id, amount=amount_cents)
+    # add idempotency key so retried charges don't double-bill the customer
+    return stripe.Charge.create(customer=customer_id, amount=amount_cents,
+                                idempotency_key=key)
"""

UNRELATED_QUERY = "configure kubernetes nginx ingress controller TLS certificate renewal"


def show(title: str, rows: list[dict]) -> None:
    print(f"  {title}:")
    for i, r in enumerate(rows, 1):
        score = r.get("score", r.get("distance", r.get("rank")))
        print(f"    {i}. {r['path']:22} score={score}")


async def main() -> int:
    ok = True
    client = get_memory_client()

    # --- show the two lanes for the stripe diff (one embed call) ---
    emb = await asyncio.to_thread(embed_query, STRIPE_DIFF)
    vec = await client.vector_search(REPO, emb, 5)
    kw = await client.keyword_search(REPO, STRIPE_DIFF, 5)
    print("[lanes for stripe diff]")
    show("vector (DiskANN)", vec)
    show("keyword (FTS)", kw)

    # --- Query A: stripe diff -> stripe.py in top-3 ---
    a = await retrieve(REPO, STRIPE_DIFF, k=3)
    print("\n[Query A - stripe diff] fused top-3:")
    show("fused (RRF)", a)
    top3 = [r["path"] for r in a]
    a_ok = "billing/stripe.py" in top3
    print(f"  -> billing/stripe.py in top-3? {a_ok}")
    ok &= a_ok

    # --- Query B: unrelated -> stripe.py must NOT be rank 1 ---
    b = await retrieve(REPO, UNRELATED_QUERY, k=3)
    print("\n[Query B - unrelated] fused top-3:")
    show("fused (RRF)", b)
    b_top = b[0]["path"] if b else None
    b_ok = b_top != "billing/stripe.py"
    print(f"  -> top hit is NOT billing/stripe.py? {b_ok} (top={b_top})")
    ok &= b_ok

    # --- cache: identical query returns instantly from Redis (best-effort) ---
    again = await retrieve(REPO, STRIPE_DIFF, k=3)
    cache_ok = [r["id"] for r in again] == [r["id"] for r in a]
    print(f"\n[cache] repeat query matches first result? {cache_ok}")

    await client.close()
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
