import { useCallback, useEffect, useState } from "react";
import { Cloud, ExternalLink, RefreshCw, Search, Sun, Thermometer, Wind } from "lucide-react";
import ChartCard from "./ChartCard";
import { errorMessage, getEnergyIntelligence, getEnergyResearch } from "../services/api";

const researchTopics = [
  ["solar", "Solar developments"],
  ["storage", "Storage innovation"],
  ["grid", "Grid advisories"],
  ["india_policy", "India energy policy"],
  ["community_energy", "Community energy"],
  ["climate_risks", "Climate energy risks"],
  ["renewables", "Renewables"],
];

export default function EnergyIntelligenceCenter() {
  const [location, setLocation] = useState("New Delhi");
  const [weatherData, setWeatherData] = useState(null);
  const [weatherLoading, setWeatherLoading] = useState(true);
  const [weatherError, setWeatherError] = useState("");
  const [topic, setTopic] = useState("solar");
  const [research, setResearch] = useState(null);
  const [researchLoading, setResearchLoading] = useState(true);
  const [researchError, setResearchError] = useState("");

  const loadWeather = useCallback(async () => {
    setWeatherLoading(true);
    setWeatherError("");
    try {
      setWeatherData(await getEnergyIntelligence(location.trim()));
    } catch (requestError) {
      setWeatherError(errorMessage(requestError));
    } finally {
      setWeatherLoading(false);
    }
  }, [location]);

  const loadResearch = useCallback(async () => {
    setResearchLoading(true);
    setResearchError("");
    try {
      setResearch(await getEnergyResearch(topic));
    } catch (requestError) {
      setResearchError(errorMessage(requestError));
    } finally {
      setResearchLoading(false);
    }
  }, [topic]);

  useEffect(() => {
    getEnergyIntelligence("New Delhi")
      .then(setWeatherData)
      .catch((requestError) => setWeatherError(errorMessage(requestError)))
      .finally(() => setWeatherLoading(false));
    getEnergyResearch("solar")
      .then(setResearch)
      .catch((requestError) => setResearchError(errorMessage(requestError)))
      .finally(() => setResearchLoading(false));
  }, []);

  const weather = weatherData?.weather;
  const insights = weatherData?.weather_insights;

  return (
    <section className="intelligence-center page-stack" aria-labelledby="intelligence-title">
      <div className="page-heading">
        <div>
          <h1 id="intelligence-title">EcoPulse Energy Intelligence Center</h1>
          <p>External weather, independent weather-risk signals, and attributed energy research.</p>
        </div>
        <span className="simulated-pill"><span /> External sources · planning only</span>
      </div>

      <div className="two-column">
        <ChartCard title="Live weather intelligence" subtitle="WeatherAPI observations and forecast; not EcoPulse energy measurements.">
          <form className="intelligence-controls" onSubmit={(event) => { event.preventDefault(); loadWeather(); }}>
            <label htmlFor="weather-location">Location</label>
            <input id="weather-location" value={location} maxLength={120} onChange={(event) => setLocation(event.target.value)} />
            <button type="submit" className="button secondary" disabled={weatherLoading || !location.trim()}>
              <RefreshCw size={14} /> {weatherLoading ? "Refreshing…" : "Refresh"}
            </button>
          </form>
          {weatherLoading && !weatherData && <div className="empty-panel">Loading external weather…</div>}
          {weatherError && <div className="error-banner" role="alert">{weatherError}<button onClick={loadWeather}>Retry</button></div>}
          {weather ? (
            <div className="page-stack intelligence-weather">
              <div className="weather-current">
                <div>
                  <strong>{weather.location.name}{weather.location.region ? `, ${weather.location.region}` : ""}</strong>
                  <span>{weather.location.country} · {weather.current.condition}</span>
                </div>
                <strong className="weather-temperature">{weather.current.temperature_c}°C</strong>
              </div>
              <div className="weather-facts">
                <span><Cloud size={15} /> Cloud {weather.current.cloud_cover_percent}%</span>
                <span><Thermometer size={15} /> Humidity {weather.current.humidity_percent}%</span>
                <span><Wind size={15} /> Wind {weather.current.wind_kph} km/h</span>
                <span>Rain {weather.current.precipitation_mm} mm</span>
              </div>
              <div className="intelligence-updated">
                Observed {weather.current.observed_at || "time unavailable"} · retrieved {new Date(weather.fetched_at).toLocaleString()}
              </div>
              <div>
                <h3 className="intelligence-subheading">Hourly forecast</h3>
                {weather.hourly?.length ? (
                  <div className="weather-hourly">
                    {weather.hourly.slice(0, 12).map((hour) => (
                      <div className="weather-hour" key={hour.time}>
                        <strong>{new Date(hour.time.replace(" ", "T")).toLocaleTimeString([], { hour: "numeric" })}</strong>
                        <span>{hour.temperature_c}°C</span>
                        <small>Cloud {hour.cloud_cover_percent}% · Rain {hour.chance_of_rain_percent}%</small>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty-state">Hourly forecast is unavailable.</div>}
              </div>
              <div className="weather-daily">
                <h3 className="intelligence-subheading">Daily outlook</h3>
                {weather.daily?.map((day) => (
                  <div className="weather-day" key={day.date}>
                    <strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}</strong>
                    <span>{day.minimum_temperature_c}° / {day.maximum_temperature_c}°C</span>
                    <small>{day.condition} · Rain {day.chance_of_rain_percent}%</small>
                  </div>
                ))}
              </div>
              <div className="intelligence-alerts">
                <h3 className="intelligence-subheading">Weather alerts</h3>
                {weather.alerts?.length ? weather.alerts.map((alert, index) => (
                  <div className="notice" key={`${alert.title}-${index}`}>
                    <strong>{alert.title}</strong>{alert.description ? ` — ${alert.description}` : ""}
                    {alert.severity ? ` · ${alert.severity}` : ""}
                  </div>
                )) : <div className="empty-state">No alerts were returned for this forecast.</div>}
              </div>
            </div>
          ) : !weatherLoading && !weatherError ? <div className="empty-panel">Weather data is not configured.</div> : null}
        </ChartCard>

        <ChartCard title="Predictive weather insights" subtitle="Relative planning signals; do not alter the ML forecast or simulator dispatch.">
          {insights?.available ? (
            <div className="page-stack">
              <div className="result-grid intelligence-metrics">
                <div className="result-card"><span>Relative solar potential</span><strong>{insights.relative_solar_potential_change_percent > 0 ? "+" : ""}{insights.relative_solar_potential_change_percent}% <small>vs cloud assumption</small></strong></div>
                <div className="result-card"><span>Temperature-related demand adjustment</span><strong>{insights.estimated_temperature_related_demand_adjustment_percent > 0 ? "+" : ""}{insights.estimated_temperature_related_demand_adjustment_percent}% <small>estimated</small></strong></div>
                <div className="result-card"><span>Rain probability peak</span><strong>{insights.maximum_rain_probability_next_24h_percent}% <small>next 24 hours</small></strong></div>
                <div className="result-card"><span>Forecast temperature average</span><strong>{insights.forecast_temperature_average_c}°C <small>next 24 hours</small></strong></div>
              </div>
              <div className="notice"><Sun size={15} /> {insights.solar_signal} No solar irradiance is returned or inferred; this is a relative cloud-cover adjustment only.</div>
              <div>
                <h3 className="intelligence-subheading">Planning recommendations</h3>
                <ul className="intelligence-recommendations">
                  {insights.recommendations.map((recommendation) => <li key={recommendation}>{recommendation}</li>)}
                </ul>
              </div>
              <div className="intelligence-updated">{insights.solar_method}</div>
            </div>
          ) : <div className="empty-state">Weather-based planning signals are unavailable until a forecast is loaded.</div>}
          <div className="notice intelligence-distinction">
            Existing RandomForest predictions, WeatherAPI-based relative adjustments, and simulated dispatch are distinct outputs. Real weather does not make simulated energy measurements real.
          </div>
        </ChartCard>
      </div>

      <ChartCard title="Energy research intelligence" subtitle="Recent third-party search snippets; treat as unverified until checked at the source.">
        <form className="intelligence-controls research-controls" onSubmit={(event) => { event.preventDefault(); loadResearch(); }}>
          <label htmlFor="research-topic">Research category</label>
          <select id="research-topic" value={topic} onChange={(event) => setTopic(event.target.value)}>
            {researchTopics.map(([key, label]) => <option value={key} key={key}>{label}</option>)}
          </select>
          <button type="submit" className="button primary" disabled={researchLoading}>
            <Search size={14} /> {researchLoading ? "Searching…" : "Refresh research"}
          </button>
        </form>
        {researchLoading && !research && <div className="empty-panel">Searching attributed energy sources…</div>}
        {researchError && <div className="error-banner" role="alert">{researchError}<button onClick={loadResearch}>Retry</button></div>}
        {research?.results?.length ? (
          <div className="research-list">
            {research.results.map((item) => (
              <article className="research-item" key={item.source_url}>
                <div className="research-title">
                  <a href={item.source_url} target="_blank" rel="noreferrer">{item.title} <ExternalLink size={13} /></a>
                  <span>{item.source_domain}{item.published_date ? ` · ${item.published_date}` : " · date unavailable"}</span>
                </div>
                <p>{item.summary}</p>
              </article>
            ))}
          </div>
        ) : research && !researchLoading ? (
          <div className="empty-state">No recent results were returned for this category.</div>
        ) : null}
        {research?.fetched_at && <div className="intelligence-updated">Retrieved {new Date(research.fetched_at).toLocaleString()} · powered by Tavily. Source content is untrusted research context.</div>}
      </ChartCard>
    </section>
  );
}
