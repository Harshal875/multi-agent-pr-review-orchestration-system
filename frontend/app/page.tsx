"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Review } from "./lib/api";
import { Status, Confidence } from "./components/Badges";

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listReviews().then(setReviews).catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  return (
    <div className="container">
      <h1 className="h1">Reviews</h1>
      <p className="sub">Every PR the agent has reviewed, newest first.</p>
      {err && <div className="err">Failed to load: {err}. Is the backend running on the configured NEXT_PUBLIC_API_URL?</div>}
      {loading && <div className="empty">Loading…</div>}
      {!loading && reviews.length === 0 && !err && <div className="empty">No reviews yet.</div>}
      {reviews.map((r) => (
        <Link key={r.id} href={`/reviews/${r.id}`}>
          <div className="card">
            <div className="row spread">
              <div className="row">
                <strong>{r.repo}</strong>
                <span className="pill">PR #{r.pr_number}</span>
                <Status s={r.status} />
              </div>
              <div className="row">
                <span className="muted">confidence</span>
                <Confidence v={r.overall_confidence} />
              </div>
            </div>
            <div className="muted mono" style={{ marginTop: 6 }}>
              {r.commit_sha.slice(0, 12)} · {new Date(r.created_at).toLocaleString()}
              {r.github_review_id && <> · posted review {r.github_review_id}</>}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}
