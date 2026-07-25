import { SEVERITY_COLOR } from "../lib/api";

export function Severity({ s }: { s: string }) {
  const c = SEVERITY_COLOR[s] || "#9ca3af";
  return <span className="badge" style={{ background: c + "22", color: c }}>{s}</span>;
}

const STATUS_COLOR: Record<string, string> = {
  posted: "#7ee787", awaiting_human: "#fbbf24", rejected: "#f87171",
  pending: "#8a93a6",
};
export function Status({ s }: { s: string }) {
  const c = STATUS_COLOR[s] || "#8a93a6";
  return <span className="badge" style={{ background: c + "22", color: c }}>{s}</span>;
}

export function Confidence({ v }: { v: number | null }) {
  if (v == null) return <span className="muted">—</span>;
  const c = v >= 0.75 ? "#7ee787" : "#fbbf24";
  return <span style={{ color: c, fontWeight: 600 }}>{v.toFixed(2)}</span>;
}
