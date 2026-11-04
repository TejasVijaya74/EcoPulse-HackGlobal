import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "../components/ChartCard";

const timeLabel = (value) => new Date(value).toLocaleTimeString([], { hour: "numeric" });

export default function Forecast({ forecast }) {
  const rows = forecast?.forecast || [];
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Energy forecast</h1>
          <p>24-hour machine-learning forecast using the selected weather source and synthetic demand history.</p>
        </div>
        <span className="simulated-pill"><span /> {forecast?.weather_label || "Forecast estimate"}</span>
      </div>
      {forecast && (
        <div className="notice">
          Weather input: <strong>{forecast.weather_label}</strong>.
          {forecast.weather_fallback_reason ? ` ${forecast.weather_fallback_reason}` : ""}
          {" "}Weather data by <a href={forecast.weather_attribution_url} target="_blank" rel="noreferrer">Open-Meteo</a>.
          Forecast values remain machine-learning predictions, not direct weather measurements.
        </div>
      )}
      <ChartCard title="Solar and household demand" subtitle="Predicted power, kW">
        {rows.length ? (
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={rows} margin={{ top: 12, right: 20, left: -12, bottom: 0 }}>
              <CartesianGrid stroke="#edf0ed" vertical={false} />
              <XAxis dataKey="timestamp" tickFormatter={timeLabel} minTickGap={20} tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
              <Legend />
              <Line type="monotone" dataKey="solar_generation_kw" name="Solar generation" stroke="#35815f" strokeWidth={2.4} dot={false} />
              <Line type="monotone" dataKey="solar_lower_kw" name="Solar lower band" stroke="#a8cbb2" strokeDasharray="4 4" strokeWidth={1} dot={false} />
              <Line type="monotone" dataKey="solar_upper_kw" name="Solar upper band" stroke="#a8cbb2" strokeDasharray="4 4" strokeWidth={1} dot={false} />
              <Line type="monotone" dataKey="household_demand_kw" name="Household demand" stroke="#5371a7" strokeWidth={2.2} dot={false} />
              <Line type="monotone" dataKey="net_energy_balance_kw" name="Net balance" stroke="#d59046" strokeWidth={1.8} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        ) : <div className="empty-chart">Forecast is loading or unavailable.</div>}
      </ChartCard>
      <div className="two-column">
        <ChartCard title="Forecast method" subtitle="Random forest regression">
          <p className="body-copy">Separate RandomForestRegressor models forecast solar generation and household load. Training and evaluation use chronological splits.</p>
          <p className="body-copy">Band: {forecast?.uncertainty_label || "Approximate uncertainty band."}</p>
        </ChartCard>
        <ChartCard title="Held-out model scores" subtitle="Model compared with previous-hour baseline">
          {forecast?.model_metrics ? (
            <div className="score-list">
              {Object.entries(forecast.model_metrics).map(([target, values]) => (
                <div className="score-row" key={target}>
                  <strong>{target === "solar_generation" ? "Solar" : "Demand"}</strong>
                  <span>MAE {values.model?.mae?.toFixed(2)} kW</span>
                  <span>RMSE {values.model?.rmse?.toFixed(2)} kW</span>
                  <span>R² {values.model?.r2?.toFixed(2)}</span>
                  <span>Baseline MAE {values.baseline?.mae?.toFixed(2)} kW</span>
                </div>
              ))}
            </div>
          ) : <div className="empty-chart">Model evaluation metrics are unavailable.</div>}
        </ChartCard>
      </div>
      <div className="footnote">Solar weather features may use Open-Meteo or a clearly labeled synthetic fallback. Household demand remains an ML estimate from synthetic demand history; not an operational dispatch instruction.</div>
    </div>
  );
}
