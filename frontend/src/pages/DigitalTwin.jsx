import { BatteryCharging, House, Network, Sun } from "lucide-react";

function FlowNode({ icon: Icon, title, value, unit, note, state }) {
  return (
    <div className={`flow-node ${state || ""}`}>
      <div className="flow-icon"><Icon size={22} /></div>
      <strong>{title}</strong>
      <span className="flow-value">{value ?? "—"} {unit}</span>
      <small>{note}</small>
    </div>
  );
}

export default function DigitalTwin({ telemetry, dashboard }) {
  const live = telemetry || dashboard?.current || {};
  const positive = Number(live.net_balance_kw || 0) >= 0;
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Digital twin</h1>
          <p>Interactive 2D view of simulated energy flows across the community.</p>
        </div>
        <span className="live-status"><span /> {telemetry ? "WebSocket · simulated values" : "REST · simulated values"}</span>
      </div>
      <section className="panel twin-panel">
        <div className="twin-flow">
          <FlowNode icon={Sun} title="Solar panels" value={live.solar_generation_kw} unit="kW" note="Renewable generation" />
          <div className={`flow-arrow ${positive ? "active" : ""}`}><span /></div>
          <FlowNode icon={Network} title="Energy controller" value={live.net_balance_kw} unit="kW net" note={live.operating_state || "Balancing"} state="controller" />
          <div className={`flow-arrow ${live.storage_soc_percent > 0 ? "active" : ""}`}><span /></div>
          <FlowNode icon={BatteryCharging} title="Flywheel storage" value={live.storage_level_kwh} unit="kWh" note={`${live.storage_soc_percent ?? "—"}% state of charge`} state="storage" />
          <div className={`flow-arrow ${!positive ? "active" : ""}`}><span /></div>
          <FlowNode icon={House} title="Neighborhood" value={live.household_demand_kw} unit="kW" note="Household demand" state="houses" />
        </div>
        <div className="grid-connection">
          <span className="grid-line" />
          <div><Network size={18} /> Utility grid</div>
          <span>Import {live.grid_imports_kwh ?? 0} kWh · Export {live.grid_exports_kwh ?? 0} kWh</span>
        </div>
      </section>
      <div className="notice">All nodes and values are a software simulation of an abstract flywheel storage system; this does not represent a physically deployed neighborhood installation.</div>
    </div>
  );
}
