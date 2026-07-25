"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, EconSummary, ReviewCost, fmtUsd } from "../lib/api";

export default function EconomicsPage() {
  const [sum, setSum] = useState<EconSummary | null>(null);
  const [costs, setCosts] = useState<ReviewCost[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.econSummary(), api.reviewCosts()])
      .then(([s, c]) => { setSum(s); setCosts(c); })
      .catch((e) => setErr(String(e)));
  }, []);

  const pct = sum ? Math.min((sum.today_cost_usd / sum.daily_cap_usd) * 100, 100) : 0;

  return (
    <div className="container">
      <h1 className="h1">Economics</h1>
      <p className="sub">Live spend against the daily budget cap (BudgetGuard blocks LLM calls once tripped).</p>
      {err && <div className="err">Failed to load: {err}</div>}
      {sum && (
        <>
          <div className="grid" style={{ marginBottom: 18 }}>
            <div className="card"><div className="muted">Today's spend</div>
              <div className="stat">{fmtUsd(sum.today_cost_usd)}</div></div>
            <div className="card"><div className="muted">Daily cap</div>
              <div className="stat">${sum.daily_cap_usd.toFixed(2)}</div></div>
            <div className="card"><div className="muted">Budget status</div>
              <div className="stat" style={{ color: sum.blocked ? "#f87171" : "#7ee787" }}>
                {sum.blocked ? "BLOCKED" : "OK"}</div></div>
            <div className="card"><div className="muted">Auto-post threshold</div>
              <div className="stat">{sum.confidence_threshold.toFixed(2)}</div></div>
          </div>
          <div className="card">
            <div className="row spread"><span className="muted">daily budget used</span>
              <span className="muted">{pct.toFixed(1)}%</span></div>
            <div className="wf-bar-track" style={{ height: 14, marginTop: 8 }}>
              <div className="wf-bar" style={{ left: 0, width: `${pct}%`,
                background: sum.blocked ? "#f87171" : "#7ee787" }} />
            </div>
          </div>
        </>
      )}

      <h2 className="h1" style={{ fontSize: 17, marginTop: 24 }}>Cost per review</h2>
      <div className="card">
        {costs.length === 0 ? <div className="empty">No cost data yet.</div> : (
          <table>
            <thead><tr><th>Review</th><th>Agents</th><th>Max confidence</th><th>Cost</th></tr></thead>
            <tbody>
              {costs.map((c) => (
                <tr key={c.review_id}>
                  <td><Link href={`/reviews/${c.review_id}`} className="mono">{c.review_id.slice(0, 8)}…</Link></td>
                  <td>{c.agents_used ?? "—"}</td>
                  <td>{c.max_confidence != null ? c.max_confidence.toFixed(2) : "—"}</td>
                  <td className="mono">{fmtUsd(c.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
