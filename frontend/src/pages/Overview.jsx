import { useMemo } from "react";
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
import { Activity, BatteryCharging, Coins, Sun, Zap } from "lucide-react";
import MetricCard from "../components/MetricCard";
import ChartCard from "../components/ChartCard";

const shortTime = (value) => new Date(value).toLocaleTimeString([], { hour: "numeric" });

export default function Overview({ dashboard, credits, telemetry }) {
  const series = useMemo(() => dashboard?.series?.slice(0, 24) || [], [dashboard]);
  const metrics = dashboard?.metrics || {};
  const current = telemetry || dashboard?.current || {};
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
          Forecast weather source: <strong>{dashboard.weather.label}</strong>.
          {dashboard.weather.fallback_reason ? ` ${dashboard.weather.fallback_reason}` : ""}
          {" "}Weather data by <a href={dashboard.weather.attribution_url} target="_blank" rel="noreferrer">Open-Meteo</a>.
        </div>
      )}
      <div className="metric-grid">
        <MetricCard label="Solar generation" value={current.solar_generation_kw ?? "—"} unit="kW" icon={Sun} detail="Current interval" />
        <MetricCard label="Household demand" value={current.household_demand_kw ?? "—"} unit="kW" icon={Zap} detail="Current interval" tone="blue" />
        <MetricCard label="Flywheel state of charge" value={current.storage_soc_percent ?? "—"} unit="%" icon={BatteryCharging} detail={`${current.storage_level_kwh ?? "—"} kWh stored`} tone="amber" />
        <MetricCard label="Grid dependency" value={metrics.grid_dependency_percent ?? "—"} unit="%" icon={Activity} detail={`${metrics.grid_imports_kwh ?? "—"} kWh imported`} tone="purple" />
        <MetricCard label="Renewable utilization" value={metrics.renewable_utilization_percent ?? "—"} unit="%" icon={Sun} detail={`${metrics.curtailed_energy_kwh ?? "—"} kWh curtailed`} />
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
