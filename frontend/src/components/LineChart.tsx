// Dependency-free SVG line chart for telemetry series.
export function LineChart({ title, unit, values, times }: { title: string; unit: string; values: (number | null)[]; times: string[] }) {
  const W = 320, H = 96, P = 6;
  const pts = values.map((v, i) => ({ v, i })).filter((p): p is { v: number; i: number } => p.v !== null);
  const latest = pts.length ? pts[pts.length - 1].v : null;
  if (pts.length < 2) {
    return (
      <figure className="chart">
        <figcaption><span>{title}</span><strong>{latest ?? "—"} {latest !== null && unit}</strong></figcaption>
        <p className="note">Not enough samples yet.</p>
      </figure>
    );
  }
  const min = Math.min(...pts.map((p) => p.v)), max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const x = (i: number) => P + (i / Math.max(values.length - 1, 1)) * (W - 2 * P);
  const y = (v: number) => H - P - ((v - min) / span) * (H - 2 * P);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  return (
    <figure className="chart">
      <figcaption><span>{title}</span><strong>{latest} {unit}</strong></figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${pts.length} samples from ${min} to ${max} ${unit}, latest ${latest}`}>
        <path d={d} className="chart__line" />
      </svg>
      <p className="chart__range">Range {min}–{max} {unit}, {new Date(times[0]).toLocaleTimeString()} to {new Date(times[times.length - 1]).toLocaleTimeString()}</p>
    </figure>
  );
}
