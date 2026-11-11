import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, BatteryCharging, Coins, Send, Sun, Zap } from "lucide-react";
import MetricCard from "../components/MetricCard";
import ChartCard from "../components/ChartCard";
import EnergyIntelligenceCenter from "../components/EnergyIntelligenceCenter";
import { askEnergyAdvisor, errorMessage } from "../services/api";

const shortTime = (value) => new Date(value).toLocaleTimeString([], { hour: "numeric" });

export default function Overview({ dashboard, credits, telemetry, publicDemoMode }) {
  const series = useMemo(() => dashboard?.series?.slice(0, 24) || [], [dashboard]);
  const metrics = dashboard?.metrics || {};
  const current = telemetry || dashboard?.current || {};
  const carbon = dashboard?.carbon_impact;
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Community overview</h1>
          <p>Simulated neighborhood energy performance at a glance.</p>
        </div>
        <div className="overview-status">
          <strong>{current.operating_state || "Awaiting telemetry"}</strong>
          <span className="simulated-pill"><span /> Simulation data</span>
        </div>
      </div>
      {dashboard?.weather && (
        <div className="notice">
          {dashboard.weather.source === "open-meteo" ? "Live weather input" : "Synthetic weather fallback"} for forecast:{" "}
          <strong>{dashboard.weather.label}</strong>.
          {dashboard.weather.fallback_reason ? ` ${dashboard.weather.fallback_reason}` : ""}
          {" "}Weather data by <a href={dashboard.weather.attribution_url} target="_blank" rel="noreferrer">Open-Meteo</a>.
          {" "}Energy generation, demand, storage, and grid values below are simulated.
        </div>
      )}
      <ChartCard
        title="Carbon impact"
        subtitle="Simulated estimate based on grid imports; not measured emissions."
      >
        <div className="result-grid">
          <Result label="Community grid emissions" value={carbon?.community?.estimated_emissions_kg_co2} unit="kg CO₂" />
          <Result label="Per household" value={carbon?.per_household?.estimated_emissions_kg_co2} unit="kg CO₂" />
          <Result label="Avoided vs matched baseline" value={carbon?.avoided_emissions_kg_co2} unit="kg CO₂" />
          <Result label="Avoided per household" value={carbon?.avoided_emissions_per_household_kg_co2} unit="kg CO₂" />
        </div>
        <p className="carbon-source">
          {carbon?.grid_emissions_factor
            ? `Factor: ${carbon.grid_emissions_factor.value} ${carbon.grid_emissions_factor.units} · ${carbon.grid_emissions_factor.source} · reporting year ${carbon.grid_emissions_factor.reporting_year}.`
            : "Emissions factor details unavailable."}
          {" "}Based on grid imports only; solar generation and storage charging/discharging are not counted separately.
          {" "}The configured CEA citation and reporting year have not been independently verified.
          {carbon?.available === false ? ` ${carbon.unavailable_reason}` : ""}
        </p>
      </ChartCard>

      <AdvisorPanel dashboard={dashboard} publicDemoMode={publicDemoMode} />
      <EnergyIntelligenceCenter />

      <div className="metric-grid">
        <MetricCard label="Solar generation" value={metrics.renewable_generated_kwh ?? "—"} unit="kWh" icon={Sun} detail={`${current.solar_generation_kw ?? "—"} kW current interval`} />
        <MetricCard label="Household consumption" value={metrics.household_consumption_kwh ?? "—"} unit="kWh" icon={Zap} detail={`${current.household_demand_kw ?? "—"} kW current interval`} tone="blue" />
        <MetricCard label="Stored energy (end)" value={metrics.ending_storage_kwh ?? current.storage_level_kwh ?? "—"} unit="kWh" icon={BatteryCharging} detail={`${metrics.energy_stored_kwh ?? "—"} kWh charged during run`} tone="amber" />
        <MetricCard label="Energy discharged" value={metrics.energy_discharged_kwh ?? "—"} unit="kWh" icon={Activity} detail="Total delivered by storage" tone="amber" />
        <MetricCard label="Grid imports" value={metrics.grid_imports_kwh ?? "—"} unit="kWh" icon={Zap} detail="Total imported from grid" tone="purple" />
        <MetricCard label="Grid exports" value={metrics.grid_exports_kwh ?? "—"} unit="kWh" icon={Activity} detail="Total exported to grid" />
        <MetricCard label="Grid dependency" value={metrics.grid_dependency_percent ?? "—"} unit="%" icon={Activity} detail={`${metrics.grid_imports_kwh ?? "—"} kWh imported`} tone="purple" />
        <MetricCard label="Renewable utilization" value={metrics.renewable_utilization_percent ?? "—"} unit="%" icon={Sun} detail={`${metrics.curtailed_energy_kwh ?? "—"} kWh curtailed`} />
        <MetricCard label="Unserved energy" value={metrics.unserved_energy_kwh ?? "—"} unit="kWh" icon={Zap} detail="Demand not met by local supply or grid" tone="blue" />
        <MetricCard label="Community credits" value={credits?.total_credits ?? "—"} unit="credits" icon={Coins} detail="Simulated incentives" tone="amber" />
      </div>

      <div className="chart-grid">
        <ChartCard title="Generation and demand" subtitle="Hourly power, kW">
          {series.length ? (
            <ResponsiveContainer width="100%" height={265}>
              <LineChart data={series} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="#edf0ed" vertical={false} />
                <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} />
                <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                <Legend />
                <Line type="monotone" dataKey="solar_generation_kw" name="Solar" stroke="#35815f" strokeWidth={2.2} dot={false} />
                <Line type="monotone" dataKey="household_demand_kw" name="Demand" stroke="#5371a7" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="empty-chart">Simulation data will appear here.</div>}
        </ChartCard>
        <ChartCard title="Flywheel storage" subtitle="Stored energy, kWh">
          {series.length ? (
            <ResponsiveContainer width="100%" height={265}>
              <AreaChart data={series} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="#edf0ed" vertical={false} />
                <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} />
                <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                <Area type="monotone" dataKey="storage_level_kwh" name="Storage" stroke="#35815f" fill="#dcebe1" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : <div className="empty-chart">Simulation data will appear here.</div>}
        </ChartCard>
        <ChartCard title="Grid exchange" subtitle="Imports and exports, kWh" className="wide-chart">
          {series.length ? (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={series} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="#edf0ed" vertical={false} />
                <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} />
                <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                <Legend />
                <Area type="monotone" dataKey="grid_import_kwh" name="Grid imports" stroke="#d59046" fill="#f7eadb" />
                <Area type="monotone" dataKey="grid_export_kwh" name="Grid exports" stroke="#35815f" fill="#dcebe1" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <div className="empty-chart">Simulation data will appear here.</div>}
        </ChartCard>
      </div>
      <div className="footnote">Latest scenario: {dashboard?.scenario || "—"} · Last simulation: {dashboard?.generated_at ? new Date(dashboard.generated_at).toLocaleString() : "not yet run"}</div>
    </div>
  );
}

function Result({ label, value, unit }) {
  const display = typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "Unavailable";
  return (
    <div className="result-card">
      <span>{label}</span>
      <strong>{display} <small>{unit}</small></strong>
    </div>
  );
}

function AdvisorPanel({ dashboard, publicDemoMode }) {
  const [question, setQuestion] = useState("");
  const [researchTopic, setResearchTopic] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setAsking(true);
    setError("");
    setAnswer("");
    try {
      const response = await askEnergyAdvisor(
        question.trim(),
        publicDemoMode ? "" : researchTopic,
      );
      setAnswer(response.answer);
    } catch (requestError) {
      setError(`${errorMessage(requestError)} Energy monitoring remains available.`);
    } finally {
      setAsking(false);
    }
  };

  return (
    <ChartCard
      title="Ask EcoPulse"
      subtitle="Optional Groq-powered guidance grounded in backend simulation results."
    >
      <form className="advisor-form" onSubmit={submit}>
        <label htmlFor="advisor-question">Ask about energy balance, grid dependency, curtailment, storage, or carbon impact.</label>
        <textarea
          id="advisor-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={1000}
          rows={3}
          placeholder="For example: What is driving grid imports in this simulation?"
          required
        />
        {publicDemoMode ? (
          <p className="body-copy">Public demo answers do not trigger extra research requests. Explore the separate Energy Research panel.</p>
        ) : (
          <>
            <label htmlFor="advisor-research-topic">Optional research context</label>
            <select id="advisor-research-topic" value={researchTopic} onChange={(event) => setResearchTopic(event.target.value)}>
              <option value="">No external research</option>
              <option value="solar">Solar developments</option>
              <option value="storage">Storage innovation</option>
              <option value="grid">Grid advisories</option>
              <option value="india_policy">India energy policy</option>
              <option value="community_energy">Community energy</option>
              <option value="climate_risks">Climate energy risks</option>
              <option value="renewables">Renewables</option>
            </select>
          </>
        )}
        <div className="advisor-actions">
          <span>Answers use available simulation figures only. Missing values should be identified.</span>
          <button className="button primary" type="submit" disabled={asking || !dashboard?.metrics}>
            <Send size={15} /> {asking ? "Asking…" : "Ask EcoPulse"}
          </button>
        </div>
      </form>
      {error && <div className="advisor-message error" role="alert">{error}</div>}
      {answer && <div className="advisor-message" role="status">{answer}</div>}
    </ChartCard>
  );
}
