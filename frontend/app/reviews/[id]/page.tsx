"use client";
import { useEffect, useState } from "react";
import { api, Review, AuditFinding, TrailEvent } from "../../lib/api";
import { Severity, Status, Confidence } from "../../components/Badges";

interface FlatEvent extends TrailEvent { agent: string; }

const EVENT_COLOR: Record<string, string> = {
  "span.start": "#4b5563", "retrieval": "#6ea8fe", "tool.call": "#a78bfa",
  "llm.call": "#7ee787", "span.end": "#4b5563",
};

function Waterfall({ findings }: { findings: AuditFinding[] }) {
  // Flatten every finding's trail, tag with its agent, dedup identical rows.
  const seen = new Set<string>();
  const events: FlatEvent[] = [];
  for (const f of findings) {
    for (const e of f.trail) {
      const key = `${f.agent_type}|${e.ts}|${e.event_type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      events.push({ ...e, agent: f.agent_type });
    }
  }
  events.sort((a, b) => a.ts.localeCompare(b.ts));
  if (events.length === 0) return <div className="empty">No trace events.</div>;

  const t0 = new Date(events[0].ts).getTime();
  const t1 = Math.max(...events.map((e) => new Date(e.ts).getTime() + (e.latency_ms || 0)));
  const total = Math.max(t1 - t0, 1);

  return (
    <div>
      {events.map((e, i) => {
        const start = new Date(e.ts).getTime() - t0;
        const left = (start / total) * 100;
        const width = Math.max(((e.latency_ms || 0) / total) * 100, 0.8);
        const color = e.outcome === "error" ? "#f87171" : (EVENT_COLOR[e.event_type] || "#6ea8fe");
        const meta = e.event_type === "llm.call"
          ? `${e.model || ""} · ${e.tokens_in || 0}/${e.tokens_out || 0} tok`
          : e.event_type === "retrieval" && e.payload
            ? `${e.payload.count ?? ""} chunks`
            : (e.outcome || "");
        return (
          <div className="wf-row" key={i}>
            <div className="mono">{e.agent} · {e.event_type}</div>
            <div className="wf-bar-track">
              <div className="wf-bar" style={{ left: `${left}%`, width: `${width}%`, background: color }} />
            </div>
            <div className="muted mono" style={{ textAlign: "right" }}>
              {e.latency_ms != null ? `${e.latency_ms}ms` : ""} {meta}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ReviewDetail({ params }: { params: { id: string } }) {
  const { id } = params;
  const [review, setReview] = useState<Review | null>(null);
  const [audit, setAudit] = useState<AuditFinding[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string>("");

  const load = () => {
    Promise.all([api.getReview(id), api.getAudit(id)])
      .then(([r, a]) => { setReview(r); setAudit(a); })
      .catch((e) => setErr(String(e)));
  };
  useEffect(load, [id]);

  async function dispute(findingId: string) {
    const comment = prompt("Why is this finding wrong?") || "";
    if (!comment) return;
    try { await api.dispute(findingId, comment); setNote(`Disputed ${findingId.slice(0, 8)}`); }
    catch (e) { setNote(`Dispute failed: ${e}`); }
  }

  if (err) return <div className="container"><div className="err">{err}</div></div>;
  if (!review) return <div className="container"><div className="empty">Loading…</div></div>;

  return (
    <div className="container">
      <div className="row spread">
        <h1 className="h1">{review.repo} · PR #{review.pr_number}</h1>
        <Status s={review.status} />
      </div>
      <p className="sub mono">{review.commit_sha}</p>

      <div className="card">
        <div className="row spread">
          <div className="row"><span className="muted">overall confidence</span>
            <Confidence v={review.overall_confidence} /></div>
          {review.github_review_id &&
            <a className="pill" target="_blank"
               href={`https://github.com/${review.repo}/pull/${review.pr_number}#pullrequestreview-${review.github_review_id}`}>
              view posted review ↗</a>}
        </div>
      </div>

      <h2 className="h1" style={{ fontSize: 17, marginTop: 24 }}>Trace</h2>
      <p className="sub">Every agent action for this review, reconstructed from agent_events.</p>
      <div className="card"><Waterfall findings={audit} /></div>

      <h2 className="h1" style={{ fontSize: 17, marginTop: 24 }}>Findings ({audit.length})</h2>
      {note && <p className="muted">{note}</p>}
      {audit.map((f) => {
        const c = { CRITICAL: "#f87171", HIGH: "#fb923c", MEDIUM: "#fbbf24", LOW: "#60a5fa", INFO: "#9ca3af" }[f.severity] || "#9ca3af";
        const loc = f.file_path + (f.line_start ? `:${f.line_start}${f.line_end ? "-" + f.line_end : ""}` : "");
        return (
          <div className="card" key={f.id}>
            <div className="row spread">
              <div className="row"><Severity s={f.severity} />
                <span className="pill">{f.agent_type}</span>
                <span className="mono muted">{loc}</span></div>
              <button className="btn danger" onClick={() => dispute(f.id)}>Dispute</button>
            </div>
            <div className="finding" style={{ borderLeftColor: c }}>
              <h4>{f.summary}</h4>
              <div className="rat">{f.rationale}</div>
              {f.suggestion && <div className="muted"><strong>Suggestion:</strong> {f.suggestion}</div>}
              <div className="muted" style={{ marginTop: 4 }}>confidence {f.confidence.toFixed(2)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
