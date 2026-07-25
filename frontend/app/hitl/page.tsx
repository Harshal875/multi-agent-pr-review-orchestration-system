"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, HitlItem } from "../lib/api";

export default function HitlPage() {
  const [items, setItems] = useState<HitlItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => api.listHitl().then(setItems).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  async function act(reviewId: string, kind: "approve" | "reject") {
    const reviewer = prompt("Reviewer name:", "harshal") || "reviewer";
    setBusy(reviewId);
    try {
      if (kind === "approve") {
        const r = await api.approve(reviewId, reviewer);
        setMsg(`Approved — posted review ${r.github_review_id}`);
      } else {
        await api.reject(reviewId, reviewer);
        setMsg("Rejected — nothing posted.");
      }
      await load();
    } catch (e) { setMsg(`Failed: ${e}`); }
    finally { setBusy(null); }
  }

  return (
    <div className="container">
      <h1 className="h1">Approval Queue</h1>
      <p className="sub">Reviews the gate escalated (CRITICAL findings or low confidence) — approve to post, reject to discard.</p>
      {err && <div className="err">Failed to load: {err}</div>}
      {msg && <div className="card" style={{ borderColor: "#2c5282" }}>{msg}</div>}
      {items.length === 0 && !err && <div className="empty">Queue is empty — nothing awaiting review.</div>}
      {items.map((it) => (
        <div className="card" key={it.hitl_id}>
          <div className="row spread">
            <div className="row">
              <span className="badge" style={{ background: "#fbbf2422", color: "#fbbf24" }}>{it.reason}</span>
              <Link href={`/reviews/${it.review_id}`} className="mono">{it.review_id.slice(0, 8)}…</Link>
              <span className="muted">{new Date(it.created_at).toLocaleString()}</span>
            </div>
            <div className="row">
              <button className="btn primary" disabled={busy === it.review_id}
                onClick={() => act(it.review_id, "approve")}>Approve &amp; post</button>
              <button className="btn danger" disabled={busy === it.review_id}
                onClick={() => act(it.review_id, "reject")}>Reject</button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
