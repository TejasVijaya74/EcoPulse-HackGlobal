import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Activity, BatteryCharging, Coins, LayoutDashboard, Network, Sun } from "lucide-react";
import useLiveTelemetry from "./hooks/useLiveTelemetry";
import { errorMessage, getConfig, getCredits, getDashboard, getForecast, runSimulation } from "./services/api";

const Overview = lazy(() => import("./pages/Overview"));
const Forecast = lazy(() => import("./pages/Forecast"));
const DigitalTwin = lazy(() => import("./pages/DigitalTwin"));
const Simulation = lazy(() => import("./pages/Simulation"));
const Credits = lazy(() => import("./pages/Credits"));

const navigation = [
  ["overview", "Overview", LayoutDashboard],
  ["forecast", "Forecast", Sun],
  ["twin", "Digital Twin", Network],
  ["simulation", "Simulation", Activity],
  ["credits", "Community Credits", Coins],
];

export default function App() {
  const [page, setPage] = useState("overview");
  const [dashboard, setDashboard] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [credits, setCredits] = useState(null);
  const [config, setConfig] = useState(null);
  const [simulation, setSimulation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [dashboardData, forecastData, creditsData, configData] = await Promise.all([
        getDashboard(), getForecast(), getCredits(), getConfig(),
      ]);
      setDashboard(dashboardData);
      setForecast(forecastData);
      setCredits(creditsData);
      setConfig(configData);
      setError("");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const applyTelemetryFallback = useCallback((data) => setDashboard(data), []);
  const { telemetry, connection } = useLiveTelemetry(applyTelemetryFallback);

  const handleSimulation = async (parameters) => {
    setRunning(true);
    setError("");
    try {
      const result = await runSimulation(parameters);
      setSimulation(result);
      setDashboard((current) => ({
        ...current,
        simulated: true,
        scenario: result.scenario_label,
        generated_at: result.created_at,
        current: result.series?.[0],
        metrics: result.metrics,
        series: result.series,
        baseline: result.baseline,
      }));
      await Promise.all([
        getCredits().then(setCredits),
        getForecast().then(setForecast),
      ]);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setRunning(false);
    }
  };

  const titles = Object.fromEntries(navigation.map(([key, title]) => [key, title]));
  const content = {
    overview: <Overview dashboard={dashboard} credits={credits} telemetry={telemetry} />,
    forecast: <Forecast forecast={forecast} />,
    twin: <DigitalTwin telemetry={telemetry} dashboard={dashboard} />,
    simulation: <Simulation config={config} result={simulation} running={running} onRun={handleSimulation} />,
    credits: <Credits credits={credits} />,
  }[page];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage("overview"); }}>
          <span className="brand-mark"><BatteryCharging size={21} /></span>
          <span>EcoPulse<small>COMMUNITY ENERGY</small></span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {navigation.map(([key, label, Icon]) => (
            <button key={key} className={`nav-item ${page === key ? "selected" : ""}`} onClick={() => setPage(key)}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-indicator"><span className={connection === "offline" ? "offline" : ""} /> {connection === "live" ? "WebSocket live" : connection === "offline" ? "Backend offline" : "REST fallback"}</div>
          <div className="sim-label">All energy figures are simulated</div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand"><BatteryCharging size={19} /> EcoPulse</div>
          <div className="breadcrumb">EcoPulse <span>/</span> {titles[page]}</div>
          <div className={`api-state ${error ? "error" : ""}`}><span /> {error ? "Connection issue" : loading ? "Connecting" : "API connected"}</div>
        </header>
        <div className="main-content">
          {error && <div className="error-banner" role="alert">{error}<button onClick={refresh}>Retry</button></div>}
          <Suspense fallback={<div className="loading-panel">Loading view…</div>}>
            {loading && !dashboard ? <div className="loading-panel">Connecting to the local EcoPulse API…</div> : content}
          </Suspense>
        </div>
        <footer className="page-footer">EcoPulse is a local predictive energy-management simulation · Not an operational grid controller</footer>
      </main>
    </div>
  );
}
