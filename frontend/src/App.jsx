
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Activity, BatteryCharging, Coins, LayoutDashboard, Network, Sun, X } from "lucide-react";
import useLiveTelemetry from "./hooks/useLiveTelemetry";
import {
  errorMessage,
  getApiAccessToken,
  getConfig,
  getCredits,
  getDashboard,
  getForecast,
  getSimulationHistory,
  getSimulation,
  runSimulation,
  setApiAccessToken,
  validateApiAccessToken,
} from "./services/api";

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
  ["credits", "Community Energy Bank", Coins],
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
  const [apiToken, setApiToken] = useState(getApiAccessToken);
  const [tokenDraft, setTokenDraft] = useState(getApiAccessToken);
  const [validatingToken, setValidatingToken] = useState(false);
  const [accessError, setAccessError] = useState("");
  const [accessMessage, setAccessMessage] = useState("");
  const accessDetailsRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [dashboardData, forecastData] = await Promise.all([
        getDashboard(),
        getForecast(),
      ]);

      setDashboard(dashboardData);
      setForecast(forecastData);

      // Restore the latest saved simulation after refresh.
      try {
        const history = await getSimulationHistory();
        const latestSimulation = history.items?.[0];

        if (latestSimulation) {
          const savedResult = await getSimulation(latestSimulation.id);
          setSimulation(savedResult);
        } else {
          setSimulation(null);
        }
      } catch (historyError) {
        console.error("Unable to restore simulation history:", historyError);
      }

      const [creditsResult, configResult] = await Promise.allSettled([
        getCredits(),
        getConfig(),
      ]);

      if (creditsResult.status === "fulfilled") {
        setCredits(creditsResult.value);
      } else {
        setCredits(null);
      }

      if (configResult.status === "fulfilled") {
        setConfig(configResult.value);
      } else {
        setConfig(null);
      }

      if (
        creditsResult.status === "fulfilled" &&
        configResult.status === "fulfilled"
      ) {
        setError("");
      } else {
        const failure =
          creditsResult.status === "rejected"
            ? creditsResult.reason
            : configResult.reason;

        setError(errorMessage(failure));
      }
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

  const applyTelemetryFallback = useCallback(
    (data) => setDashboard(data),
    []
  );

  const { telemetry, connection } = useLiveTelemetry(applyTelemetryFallback);

  const saveApiToken = async (event) => {
    event.preventDefault();

    const token = tokenDraft.trim();

    if (!token) {
      setAccessError("Enter a bearer token to continue.");
      setAccessMessage("");
      return;
    }

    setValidatingToken(true);
    setAccessError("");
    setAccessMessage("");

    try {
      await validateApiAccessToken(token);
      setApiAccessToken(token);
      setApiToken(token);
      setTokenDraft(token);
      setAccessMessage("Access token verified.");
      refresh();
    } catch (requestError) {
      setAccessError(errorMessage(requestError));
    } finally {
      setValidatingToken(false);
    }
  };

  const clearApiToken = () => {
    setApiAccessToken("");
    setApiToken("");
    setTokenDraft("");
    setCredits(null);
    setConfig(null);
    setAccessError("");
    setAccessMessage("");
  };

  const closeAccessDialog = () => {
    if (!accessDetailsRef.current) return;

    accessDetailsRef.current.open = false;
    accessDetailsRef.current.querySelector("summary")?.focus();
  };

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
        optimization_comparison: result.optimization_comparison,
        carbon_impact: result.carbon_impact,
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

  const titles = Object.fromEntries(
    navigation.map(([key, title]) => [key, title])
  );

  const content = {
    overview: (
      <Overview
        dashboard={dashboard}
        credits={credits}
        telemetry={telemetry}
      />
    ),
    forecast: <Forecast forecast={forecast} />,
    twin: <DigitalTwin telemetry={telemetry} dashboard={dashboard} />,
    simulation: (
      <Simulation
        config={config}
        result={simulation}
        running={running}
        onRun={handleSimulation}
      />
    ),
    credits: (
      <Credits
        credits={credits}
        loading={loading}
        error={error}
        onCreditsUpdated={setCredits}
      />
    ),
  }[page];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            setPage("overview");
          }}
        >
          <span className="brand-mark">
            <BatteryCharging size={21} />
          </span>
          <span>
            EcoPulse
            <small>COMMUNITY ENERGY</small>
          </span>
        </a>

        <div className="nav-label">WORKSPACE</div>

        <nav>
          {navigation.map(([key, label, Icon]) => (
            <button
              key={key}
              className={`nav-item ${page === key ? "selected" : ""}`}
              onClick={() => setPage(key)}
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-indicator">
            <span className={connection === "offline" ? "offline" : ""} />
            {connection === "live"
              ? "WebSocket live"
              : connection === "offline"
                ? "Backend offline"
                : "REST fallback"}
          </div>

          <div className="sim-label">
            All energy figures are simulated
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand">
            <BatteryCharging size={19} />
            EcoPulse
          </div>

          <div className="breadcrumb">
            EcoPulse <span>/</span> {titles[page]}
          </div>

          <div className="topbar-actions">
            <details className="api-access" ref={accessDetailsRef}>
              <summary>
                {apiToken ? "Access set" : "Set access"}
              </summary>

              <form
                onSubmit={saveApiToken}
                role="dialog"
                aria-labelledby="access-dialog-title"
                onKeyDown={(event) => {
                  if (event.key === "Escape") closeAccessDialog();
                }}
              >
                <div className="access-dialog-heading">
                  <strong id="access-dialog-title">Set access</strong>

                  <button
                    className="access-close"
                    type="button"
                    onClick={closeAccessDialog}
                    aria-label="Close access dialog"
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>

                <label htmlFor="api-access-token">
                  Backend bearer token
                </label>

                <input
                  id="api-access-token"
                  type="password"
                  autoComplete="off"
                  aria-invalid={Boolean(accessError)}
                  aria-describedby={
                    accessError ? "access-error" : "access-help"
                  }
                  value={tokenDraft}
                  onChange={(event) => {
                    setTokenDraft(event.target.value);
                    setAccessError("");
                    setAccessMessage("");
                  }}
                />

                <div>
                  <button
                    className="button primary"
                    type="submit"
                    disabled={validatingToken}
                  >
                    {validatingToken ? "Validating…" : "Submit"}
                  </button>

                  {apiToken && (
                    <button
                      className="button secondary"
                      type="button"
                      onClick={clearApiToken}
                      disabled={validatingToken}
                    >
                      Clear
                    </button>
                  )}
                </div>

                {accessError && (
                  <small
                    className="access-feedback error"
                    id="access-error"
                    role="alert"
                  >
                    {accessError}
                  </small>
                )}

                {accessMessage && (
                  <small
                    className="access-feedback success"
                    role="status"
                  >
                    {accessMessage}
                  </small>
                )}

                <small id="access-help">
                  Kept in this tab only; protected requests verify it with
                  the backend.
                </small>
              </form>
            </details>

            <div className={`api-state ${error ? "error" : ""}`}>
              <span />
              {error
                ? "Connection issue"
                : loading
                  ? "Connecting"
                  : "API connected"}
            </div>
          </div>
        </header>

        <div className="main-content">
          {error && (
            <div className="error-banner" role="alert">
              {error}
              <button onClick={refresh}>Retry</button>
            </div>
          )}

          <Suspense
            fallback={<div className="loading-panel">Loading view…</div>}
          >
            {loading && !dashboard ? (
              <div className="loading-panel">
                Connecting to the local EcoPulse API…
              </div>
            ) : (
              content
            )}
          </Suspense>
        </div>

        <footer className="page-footer">
          EcoPulse is a local predictive energy-management simulation ·
          Not an operational grid controller
        </footer>
      </main>
    </div>
  );
}
