import { useEffect, useState } from "react";
import { Play, RotateCcw } from "lucide-react";
import ChartCard from "../components/ChartCard";

const scenarios = [
  ["normal", "Normal conditions"],
  ["heatwave", "Heatwave"],
  ["heavy_cloud", "Heavy cloud cover"],
  ["high_demand", "High demand"],
  ["grid_outage", "Grid outage"],
  ["low_solar", "Low solar generation"],
];

export default function Simulation({ config, result, running, onRun }) {
  const [form, setForm] = useState(null);
  useEffect(() => {
    if (config) setForm({ ...config, scenario: "normal", duration_hours: 48 });
  }, [config]);

  if (!form) return <div className="loading-panel">Loading simulation configuration…</div>;
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const submit = (event) => {
    event.preventDefault();
    onRun({
      scenario: form.scenario,
      households: Number(form.households),
      solar_capacity_kw: Number(form.solar_capacity_kw),
      storage_capacity_kwh: Number(form.storage_capacity_kwh),
      initial_storage_percent: Number(form.initial_storage_percent),
      grid_import_limit_kw: Number(form.grid_import_limit_kw),
      grid_export_limit_kw: Number(form.grid_export_limit_kw),
      cloud_cover: Number(form.cloud_cover),
      temperature_c: Number(form.temperature_c),
      demand_multiplier: Number(form.demand_multiplier),
      grid_available: form.scenario === "grid_outage" ? false : Boolean(form.grid_available),
      duration_hours: 48,
      random_seed: Number(form.random_seed),
    });
  };
  const metrics = result?.metrics || {};
  const baseline = result?.baseline || {};
  const normal = result?.normal_comparison?.metrics || {};
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Scenario simulation</h1>
          <p>Adjust neighborhood assumptions and run a 48-hour dispatch simulation.</p>
        </div>
        <span className="simulated-pill"><span /> Simulated scenario</span>
      </div>
      <form className="panel simulation-form" onSubmit={submit}>
        <div className="form-grid">
          <label>Scenario
            <select value={form.scenario} onChange={(event) => set("scenario", event.target.value)}>
              {scenarios.map(([key, title]) => <option value={key} key={key}>{title}</option>)}
            </select>
          </label>
          <label>Households
            <input type="number" min="1" max="5000" value={form.households} onChange={(event) => set("households", event.target.value)} />
          </label>
          <label>Solar capacity <span>{form.solar_capacity_kw} kW</span>
            <input type="range" min="0" max="500" step="5" value={form.solar_capacity_kw} onChange={(event) => set("solar_capacity_kw", event.target.value)} />
          </label>
          <label>Flywheel capacity <span>{form.storage_capacity_kwh} kWh</span>
            <input type="range" min="0" max="1000" step="10" value={form.storage_capacity_kwh} onChange={(event) => set("storage_capacity_kwh", event.target.value)} />
          </label>
          <label>Initial storage <span>{form.initial_storage_percent}%</span>
            <input type="range" min="0" max="100" step="1" value={form.initial_storage_percent} onChange={(event) => set("initial_storage_percent", event.target.value)} />
          </label>
          <label>Cloud cover <span>{Math.round(form.cloud_cover * 100)}%</span>
            <input type="range" min="0" max="1" step="0.01" value={form.cloud_cover} onChange={(event) => set("cloud_cover", event.target.value)} />
          </label>
          <label>Temperature <span>{form.temperature_c} °C</span>
            <input type="range" min="-10" max="45" step="1" value={form.temperature_c} onChange={(event) => set("temperature_c", event.target.value)} />
          </label>
          <label>Demand multiplier <span>{Number(form.demand_multiplier).toFixed(2)}×</span>
            <input type="range" min="0.5" max="2" step="0.05" value={form.demand_multiplier} onChange={(event) => set("demand_multiplier", event.target.value)} />
          </label>
          <label className="toggle-label">Grid available
            <input type="checkbox" checked={form.grid_available} onChange={(event) => set("grid_available", event.target.checked)} />
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={() => setForm({ ...config, scenario: "normal", duration_hours: 48 })}><RotateCcw size={16} /> Reset</button>
          <button className="button primary" disabled={running}><Play size={16} /> {running ? "Running simulation…" : "Run simulation"}</button>
        </div>
      </form>

      {result ? (
        <div className="results-section">
          <div className="result-heading"><div><h2>{result.scenario_label} results</h2><p>48 hourly intervals · energy quantities in kWh unless noted.</p></div><strong>{new Date(result.created_at).toLocaleString()}</strong></div>
          <div className="result-grid">
            <Result label="Grid imports" value={metrics.grid_imports_kwh} unit="kWh" />
            <Result label="Grid exports" value={metrics.grid_exports_kwh} unit="kWh" />
            <Result label="Energy stored" value={metrics.energy_stored_kwh} unit="kWh" />
            <Result label="Energy curtailed" value={metrics.curtailed_energy_kwh} unit="kWh" />
            <Result label="Renewable utilization" value={metrics.renewable_utilization_percent} unit="%" />
            <Result label="Outage service level" value={metrics.grid_outage_served_percent} unit="%" />
            <Result label="Unserved demand" value={metrics.unserved_energy_kwh} unit="kWh" />
          </div>
          <ChartCard title="Selected scenario vs normal" subtitle="Scenario impact with the same configuration and weather seed">
            <div className="comparison-table">
              <div><strong>Measure</strong><strong>Normal</strong><strong>{result.scenario_label}</strong></div>
              <div><span>Grid imports</span><span>{normal.grid_imports_kwh} kWh</span><span>{metrics.grid_imports_kwh} kWh</span></div>
              <div><span>Grid exports</span><span>{normal.grid_exports_kwh} kWh</span><span>{metrics.grid_exports_kwh} kWh</span></div>
              <div><span>Curtailed</span><span>{normal.curtailed_energy_kwh} kWh</span><span>{metrics.curtailed_energy_kwh} kWh</span></div>
              <div><span>Unserved demand</span><span>{normal.unserved_energy_kwh} kWh</span><span>{metrics.unserved_energy_kwh} kWh</span></div>
            </div>
          </ChartCard>
          <ChartCard title="Baseline vs optimized" subtitle="Baseline has no storage; optimized uses abstract flywheel storage">
            <div className="comparison-table">
              <div><strong>Measure</strong><strong>No-storage baseline</strong><strong>Optimized operation</strong></div>
              <div><span>Grid imports</span><span>{baseline.grid_imports_kwh} kWh</span><span>{metrics.grid_imports_kwh} kWh</span></div>
              <div><span>Grid exports</span><span>{baseline.grid_exports_kwh} kWh</span><span>{metrics.grid_exports_kwh} kWh</span></div>
              <div><span>Curtailed</span><span>{baseline.curtailed_energy_kwh} kWh</span><span>{metrics.curtailed_energy_kwh} kWh</span></div>
              <div><span>Unserved demand</span><span>{baseline.unserved_energy_kwh} kWh</span><span>{metrics.unserved_energy_kwh} kWh</span></div>
            </div>
          </ChartCard>
          <div className="notice">Stored and exported energy represent routed renewable surplus. Storage efficiency, self-discharge, capacity, and power limits are applied. Credits are a simulated incentive, not money.</div>
        </div>
      ) : <div className="empty-panel">Run a scenario to see its energy balance and baseline comparison.</div>}
    </div>
  );
}

function Result({ label, value, unit }) {
  return <div className="result-card"><span>{label}</span><strong>{value ?? "—"} <small>{unit}</small></strong></div>;
}
