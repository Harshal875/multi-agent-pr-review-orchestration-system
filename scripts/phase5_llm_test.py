"""Phase 5 DoD: swapping a prompt template changes model output with zero code changes,
and swapping a routing rule changes which model serves an agent with zero code changes.
Uses the live Groq-backed llm_client against the real security prompt + a real snippet
(the sample repo's stripe.py SQL string-formatting) as the case study.

Run: python scripts/phase5_llm_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.enums import AgentType         # noqa: E402
from backend.prompts import registry               # noqa: E402
from backend.tools import llm_client, model_router  # noqa: E402

SNIPPET = '''
def record_payment(db, customer_id: str, amount_cents: int):
    query = "INSERT INTO payments (customer_id, amount) VALUES ('%s', %d)" % (
        customer_id, amount_cents,
    )
    db.execute(query)
'''


def main() -> int:
    ok = True

    # --- DoD A: real security prompt flags the real SQL string-formatting bug ---
    model = model_router.model_for(AgentType.SECURITY)
    prompt = registry.get_prompt("security")
    result = llm_client.complete(
        model=model,
        system=prompt,
        user=f"Review this diff:\n```python\n{SNIPPET}\n```",
        max_tokens=1024,
    )
    print(f"[security agent] model={model}")
    print(f"  output: {result.text[:300]!r}")
    print(f"  tokens in/out: {result.input_tokens}/{result.output_tokens}")
    found_it = any(w in result.text.lower() for w in ("sql injection", "injection", "parameteriz"))
    print(f"  -> flags SQL injection? {found_it}")
    ok &= found_it

    # --- DoD B: swap the routing rule -> a different model actually serves the call ---
    original = model_router.model_for(AgentType.DOCS)
    model_router.set_route(AgentType.DOCS, model_router.model_for(AgentType.SECURITY))
    rerouted = model_router.model_for(AgentType.DOCS)
    r2 = llm_client.complete(
        model=rerouted,
        system=registry.get_prompt("docs"),
        user="Say only: ROUTED-OK",
        max_tokens=300,
    )
    print(f"\n[routing swap] docs model {original} -> {rerouted}")
    print(f"  live call served by: {r2.model}")
    route_ok = r2.model == rerouted != original
    print(f"  -> different model actually served the call? {route_ok}")
    ok &= route_ok
    model_router.set_route(AgentType.DOCS, original)  # restore

    # --- DoD C: swap the template FILE -> the prompt sent to the model changes ---
    template_path = registry.TEMPLATES / "docs.md"
    original_text = template_path.read_text(encoding="utf-8")
    try:
        template_path.write_text(
            "You are a pirate. Whatever the user says, reply only with: ARRR MATEY",
            encoding="utf-8",
        )
        swapped_prompt = registry.get_prompt("docs")  # no code change, just re-read
        r3 = llm_client.complete(
            model=model_router.model_for(AgentType.DOCS),
            system=swapped_prompt,
            user="Review this function for documentation issues.",
            max_tokens=300,
        )
    finally:
        template_path.write_text(original_text, encoding="utf-8")  # always restore

    print(f"\n[template swap] docs.md temporarily replaced with a pirate persona")
    print(f"  output: {r3.text[:120]!r}")
    swap_ok = "arrr" in r3.text.lower() or "matey" in r3.text.lower()
    print(f"  -> output reflects the swapped template? {swap_ok}")
    ok &= swap_ok

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
