export default function MetricCard({ label, value, unit, icon: Icon, detail, tone = "green" }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>{Icon && <Icon size={18} strokeWidth={1.8} />}</div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value ?? "—"} <span>{unit}</span>
      </div>
      {detail && <div className="metric-detail">{detail}</div>}
    </article>
  );
}

