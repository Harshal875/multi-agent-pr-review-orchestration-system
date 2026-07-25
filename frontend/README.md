# AI PR-Review Dashboard (Next.js)

A read/write dashboard over the FastAPI backend (Phase 2/17): review list + detail,
a trace-waterfall reconstructed from `agent_events`, the HITL approval queue
(approve → posts to GitHub / reject / dispute), and a live economics page.

## Run

```bash
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL to your backend (default http://localhost:8000)
npm install
npm run dev            # http://localhost:3000
```

The backend must be running with CORS enabled (it is, in `backend/main.py`). HITL
mutations are RBAC-gated on the backend; this dev UI sends an `X-User-Role` header
(`viewer` for reads, `approver` for approve/reject/dispute) as a stand-in for a real
authenticated session.

## Pages
- `/` — reviews list (status, confidence, posted-review link)
- `/reviews/[id]` — findings + the full agent-event trace waterfall + per-finding dispute
- `/hitl` — approval queue: approve (posts the review to the PR), reject, dispute
- `/economics` — today's spend vs. the daily cap, budget status, per-review cost
