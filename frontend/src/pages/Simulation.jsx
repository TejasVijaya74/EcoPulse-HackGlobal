import { useEffect, useState } from "react";
import { Play, RotateCcw } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "../components/ChartCard";

const scenarios = [
  ["normal", "Normal conditions"],
  ["heatwave", "Heatwave"],
  ["heavy_cloud", "Increased cloud cover"],
  ["high_demand", "High demand"],
  ["evening_peak", "Evening demand peak"],
  ["grid_outage", "Grid outage"],
  ["low_solar", "Low solar generation"],
  ["solar_surplus", "Solar surplus"],
  ["storage_constraints", "Storage constraints"],
];

const scenarioDescriptions = {
  normal: "Reference operation with configured weather, demand, grid, and storage settings.",
  heavy_cloud: "Raises modeled cloud cover to at least 88%; solar availability is reduced.",
  high_demand: "Raises modeled community demand by 35%.",
  evening_peak: "Raises demand by 50% from 17:00 through 22:00 in the deterministic trace.",
  grid_outage: "Disables grid imports and exports; any unmet demand is reported as unserved.",
  low_solar: "Reduces modeled solar output by 58%.",
  solar_surplus: "Uses 5% base cloud cover to model a high-solar-availability case.",
  storage_constraints: "Halves configured storage charge and discharge power limits.",
};

export default function Simulation({ config, result, running, onRun, publicDemoMode }) {
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
  const optimization = result?.optimization_comparison;
  const baselineMetrics = optimization?.baseline?.metrics;
  const optimizedMetrics = optimization?.optimized?.metrics;
  const scenarioComparison = [
    { measure: "Grid imports", normal: normal.grid_imports_kwh, scenario: metrics.grid_imports_kwh },
    { measure: "Grid exports", normal: normal.grid_exports_kwh, scenario: metrics.grid_exports_kwh },
    { measure: "Unserved energy", normal: normal.unserved_energy_kwh, scenario: metrics.unserved_energy_kwh },
  ];
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Scenario simulation</h1>
          <p>{publicDemoMode ? "Run a bounded 48-hour preview; public demo runs are not saved." : "Adjust neighborhood assumptions and run a 48-hour dispatch simulation."}</p>
        </div>
        <span className="simulated-pill"><span /> Simulated scenario</span>
      </div>
      <form className="panel simulation-form" onSubmit={submit}>
        <div className="form-grid">
          <label>Scenario
            <select value={form.scenario} onChange={(event) => set("scenario", event.target.value)}>
              {scenarios.map(([key, title]) => <option value={key} key={key}>{title}</option>)}
            </select>
            <small className="scenario-description">{scenarioDescriptions[form.scenario]}</small>
          </label>
          <label>Households
            <input type="number" min="1" max={publicDemoMode ? 250 : 5000} value={form.households} onChange={(event) => set("households", event.target.value)} />
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
          <div className="result-heading"><div><h2>{result.scenario_label} results</h2><p>{result.parameters?.duration_hours ?? 48} hourly intervals · energy quantities in kWh unless noted.</p></div><strong>{new Date(result.created_at).toLocaleString()}</strong></div>
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
            <div className="scenario-chart">
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={scenarioComparison} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke="#edf0ed" vertical={false} />
                  <XAxis dataKey="measure" tickLine={false} axisLine={false} />
                  <YAxis tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="normal" name="Normal operation" fill="#8095b5" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="scenario" name={result.scenario_label} fill="#39805c" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="comparison-table">
              <div><strong>Measure</strong><strong>Normal</strong><strong>{result.scenario_label}</strong></div>
              <div><span>Grid imports</span><span>{normal.grid_imports_kwh} kWh</span><span>{metrics.grid_imports_kwh} kWh</span></div>
              <div><span>Grid exports</span><span>{normal.grid_exports_kwh} kWh</span><span>{metrics.grid_exports_kwh} kWh</span></div>
              <div><span>Curtailed</span><span>{normal.curtailed_energy_kwh} kWh</span><span>{metrics.curtailed_energy_kwh} kWh</span></div>
              <div><span>Unserved demand</span><span>{normal.unserved_energy_kwh} kWh</span><span>{metrics.unserved_energy_kwh} kWh</span></div>
            </div>
          </ChartCard>
          <ChartCard
            title="Baseline vs EcoPulse dispatch"
            subtitle={optimization
              ? `Matched ${optimization.shared_inputs.duration_hours}-hour runs · same initial storage (${optimization.shared_inputs.initial_storage_kwh} kWh) and random seed (${optimization.shared_inputs.random_seed}); baseline leaves storage idle`
              : "Existing no-storage baseline comparison"}
          >
            <div className="comparison-table">
              <div><strong>Measure</strong><strong>{optimization ? "Idle-storage baseline" : "No-storage baseline"}</strong><strong>EcoPulse dispatch</strong></div>
              <div><span>Solar generation</span><span>{baselineMetrics?.renewable_generated_kwh ?? metrics.renewable_generated_kwh} kWh</span><span>{optimizedMetrics?.renewable_generated_kwh ?? metrics.renewable_generated_kwh} kWh</span></div>
              <div><span>Household consumption</span><span>{baselineMetrics?.household_consumption_kwh ?? metrics.household_consumption_kwh} kWh</span><span>{optimizedMetrics?.household_consumption_kwh ?? metrics.household_consumption_kwh} kWh</span></div>
              <div><span>Initial / ending storage</span><span>{baselineMetrics?.initial_storage_kwh ?? 0} / {baselineMetrics?.ending_storage_kwh ?? 0} kWh</span><span>{optimizedMetrics?.initial_storage_kwh ?? metrics.initial_storage_kwh} / {optimizedMetrics?.ending_storage_kwh ?? metrics.ending_storage_kwh} kWh</span></div>
              <div><span>Energy stored / discharged</span><span>{baselineMetrics?.energy_stored_kwh ?? 0} / {baselineMetrics?.energy_discharged_kwh ?? 0} kWh</span><span>{optimizedMetrics?.energy_stored_kwh ?? metrics.energy_stored_kwh} / {optimizedMetrics?.energy_discharged_kwh ?? metrics.energy_discharged_kwh} kWh</span></div>
              <div><span>Grid imports / exports</span><span>{baselineMetrics?.grid_imports_kwh ?? baseline.grid_imports_kwh} / {baselineMetrics?.grid_exports_kwh ?? baseline.grid_exports_kwh} kWh</span><span>{optimizedMetrics?.grid_imports_kwh ?? metrics.grid_imports_kwh} / {optimizedMetrics?.grid_exports_kwh ?? metrics.grid_exports_kwh} kWh</span></div>
              <div><span>Renewable utilization</span><span>{baselineMetrics?.renewable_utilization_percent ?? "—"}%</span><span>{optimizedMetrics?.renewable_utilization_percent ?? metrics.renewable_utilization_percent}%</span></div>
              <div><span>Grid dependency</span><span>{baselineMetrics?.grid_dependency_percent ?? "—"}%</span><span>{optimizedMetrics?.grid_dependency_percent ?? metrics.grid_dependency_percent}%</span></div>
              <div><span>Unserved / curtailed</span><span>{baselineMetrics?.unserved_energy_kwh ?? baseline.unserved_energy_kwh} / {baselineMetrics?.curtailed_energy_kwh ?? baseline.curtailed_energy_kwh} kWh</span><span>{optimizedMetrics?.unserved_energy_kwh ?? metrics.unserved_energy_kwh} / {optimizedMetrics?.curtailed_energy_kwh ?? metrics.curtailed_energy_kwh} kWh</span></div>
              <div><span>Storage losses / balance error</span><span>{baselineMetrics?.storage_losses_kwh ?? "—"} / {baselineMetrics?.energy_balance_error_kwh ?? "—"} kWh</span><span>{optimizedMetrics?.storage_losses_kwh ?? metrics.storage_losses_kwh} / {optimizedMetrics?.energy_balance_error_kwh ?? metrics.energy_balance_error_kwh} kWh</span></div>
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
