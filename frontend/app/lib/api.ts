// Typed client for the FastAPI backend. All calls are browser-side (CORS is open in dev).
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// The HITL routes are RBAC-gated (Phase 11). This dev dashboard sends a role header;
// a real deployment would derive the role from an authenticated session.
const VIEWER = { "X-User-Role": "viewer" };
const APPROVER = { "X-User-Role": "approver", "Content-Type": "application/json" };

export interface Review {
  id: string; repo: string; pr_number: number; commit_sha: string;
  status: string; overall_confidence: number | null; github_review_id: string | null;
  created_at: string; posted_at: string | null;
}
export interface Finding {
  id: string; review_id: string; agent_type: string; severity: string; category: string;
  summary: string; file_path: string; line_start: number | null; line_end: number | null;
  suggestion: string | null; confidence: number; rationale: string;
}
export interface TrailEvent {
  ts: string; event_type: string; model: string | null; tokens_in: number | null;
  tokens_out: number | null; cost_usd: number | null; latency_ms: number | null;
  outcome: string | null; confidence: number | null; payload: any;
}
export interface AuditFinding extends Finding { trail: TrailEvent[]; }
export interface HitlItem {
  hitl_id: string; review_id: string; reason: string; status: string; created_at: string;
}
export interface EconSummary {
  today_cost_usd: number; daily_cap_usd: number; blocked: boolean; confidence_threshold: number;
}
export interface ReviewCost {
  review_id: string; cost_usd: number; agents_used: number | null;
  max_confidence: number | null; last_bucket: string | null;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json();
}

export const api = {
  listReviews: () => j<Review[]>("/reviews"),
  getReview: (id: string) => j<Review>(`/reviews/${id}`),
  getFindings: (id: string) => j<Finding[]>(`/reviews/${id}/findings`),
  getAudit: (id: string) => j<AuditFinding[]>(`/reviews/${id}/audit`),
  listHitl: () => j<HitlItem[]>("/hitl/reviews", { headers: VIEWER }),
  approve: (reviewId: string, reviewer: string) =>
    j<{ status: string; github_review_id: string }>(`/hitl/reviews/${reviewId}/approve`,
      { method: "POST", headers: APPROVER, body: JSON.stringify({ reviewer }) }),
  reject: (reviewId: string, reviewer: string) =>
    j<{ status: string }>(`/hitl/reviews/${reviewId}/reject`,
      { method: "POST", headers: APPROVER, body: JSON.stringify({ reviewer }) }),
  dispute: (findingId: string, comment: string) =>
    j<{ feedback_id: string }>(`/hitl/findings/${findingId}/dispute`,
      { method: "POST", headers: APPROVER, body: JSON.stringify({ comment }) }),
  econSummary: () => j<EconSummary>("/economics/summary"),
  reviewCosts: () => j<ReviewCost[]>("/economics/reviews"),
};

export const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "#f87171", HIGH: "#fb923c", MEDIUM: "#fbbf24", LOW: "#60a5fa", INFO: "#9ca3af",
};
export const fmtUsd = (n: number) => `$${n.toFixed(6)}`;
