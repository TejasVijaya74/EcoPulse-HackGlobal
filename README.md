# EcoPulse

EcoPulse is a neighborhood energy-management simulation. It forecasts solar generation and household demand, dispatches an abstract flywheel storage system, models grid exchange and curtailment, and records simulated community credits.

> **Simulation notice:** All energy flows, demand, storage, telemetry, and credits are estimates, not readings from a deployed installation. Open-Meteo weather is an optional real-world input; solar generation remains an ML prediction using weather features. Household demand is forecast from synthetic history. Credits are not money or a payment instrument.

## Features

- Deterministic hourly synthetic weather, solar, and neighborhood load data.
- Optional Open-Meteo hourly weather (temperature, cloud cover, shortwave radiation, and wind) with 30-minute response caching and synthetic fallback.
- Separate Scikit-learn `RandomForestRegressor` models for solar and demand, chronological holdout evaluation, and a previous-hour baseline.
- One-day-ahead predictions with approximate uncertainty bands.
- Capacity-based flywheel dispatch with charge/discharge efficiencies, self-discharge, and power and energy limits.
- Normal, heatwave, heavy-cloud, high-demand, grid-outage, and low-solar scenarios.
- Baseline/no-storage comparisons, grid dependency, exports, curtailment, and unserved load.
- SQLAlchemy persistence with SQLite locally and PostgreSQL for hosted deployments.
- React dashboard with forecasts, a 2D energy-flow view, simulation controls, credit ledger, REST refresh, and WebSocket telemetry with REST polling fallback.

## Local development

### Requirements

- Python 3.11 or newer
- Node.js 20 or newer (npm included)
- Windows PowerShell or Command Prompt

No paid API, API key, or cloud account is required for local development. Install Python from <https://www.python.org/downloads/> and Node.js from <https://nodejs.org/>. Verify installations:

```powershell
py --version
node --version
npm --version
```

### Quick start (Windows)

From the project directory:

```powershell
.\start.bat
```

The script creates `backend\.venv` and installs dependencies on first use, then opens backend and frontend terminal windows. Local UI: <http://localhost:5173>, API: <http://localhost:8000>, docs: <http://localhost:8000/docs>.

### Manual PowerShell setup

Backend terminal:

```powershell
cd .\backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend terminal, from the project directory:

```powershell
cd .\frontend
npm install
npm run dev
```

The backend initializes the database and trains/saves models at startup when model files are missing or incompatible. Training is not performed per forecast request. Model files and the local database live under `backend\` and are excluded from Git.

## Configuration and Open-Meteo

Copy `backend\.env.example` to `backend\.env` for optional backend overrides and `frontend\.env.example` to `frontend\.env` for local frontend URL overrides. Local persistence defaults to `backend\ecopulse.db`; weather defaults to deterministic synthetic inputs because no location is configured.

Set `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, and `WEATHER_TIMEZONE` to enable Open-Meteo. Coordinates are user-supplied; no location is hardcoded. Open-Meteo requires no API key for ordinary non-commercial usage. Weather responses are cached for 30 minutes, and request/response failures fall back to synthetic weather with a visible source label. The dashboard links to Open-Meteo attribution. Synthetic household demand forecasting is retained regardless of the weather source.

Example PowerShell settings for a terminal session:

```powershell
$env:WEATHER_LATITUDE = "47.6062"
$env:WEATHER_LONGITUDE = "-122.3321"
$env:WEATHER_TIMEZONE = "America/Los_Angeles"
```

## Forecast models

Training uses hour, weekday, month, temperature, cloud cover, irradiance, wind speed, a capacity/irradiance/cloud solar estimate, previous-hour generation/load, trailing three-hour means, and 24-hour lags. Rows are split chronologically (80% train, 20% test). MAE, RMSE, and R² are computed against a previous-hour persistence baseline. Predictions are clamped to non-negative values.

Retrain using the API:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/model/train
```

## Simulation model notes

- Solar power is estimated from installed capacity, hourly irradiance, and cloud cover.
- Demand includes overnight base use, morning/evening peaks, temperature-driven cooling load, and reproducible random variation.
- Each dispatch step prioritizes direct solar load, then storage charging in surplus conditions; remaining energy exports within the configured limit and otherwise is curtailed. During deficits, storage discharge supplies load before bounded grid imports. Grid outage imports are exactly zero; remaining unmet demand is reported.
- Storage uses `E = 0.5 × I × ω²` for ideal rotational energy and a capacity-based kWh state for operation. Charging raises stored energy by input × charging efficiency; discharging removes output ÷ discharging efficiency. Capacity, power, and state bounds are enforced.
- Stored energy is not counted as new generation. Storage losses, exports, imports, and curtailed energy are reported separately. Credits accrue only for energy accepted into storage or exported for community benefit at the configured credits/kWh rate.
- The “no-storage baseline” compares the same generated renewable and demand traces without energy storage.

## API

| Endpoint | Description |
|---|---|
| `GET /api/v1/health` | API and database health |
| `GET /api/v1/dashboard` | Latest simulation metrics, chart series, and weather-source label |
| `GET /api/v1/forecast` | Forecast and model scores |
| `POST /api/v1/simulate` | Run and persist a scenario |
| `GET /api/v1/simulation/history` | Recent simulation summaries |
| `GET /api/v1/simulation/{simulation_id}` | Detailed stored simulation |
| `GET /api/v1/credits` | Simulated incentive ledger |
| `GET /api/v1/config` | Current configuration |
| `POST /api/v1/config` | Validate and persist configuration |
| `POST /api/v1/model/train` | Retrain forecast models |
| `WS /ws/grid-telemetry` | Playback telemetry from the latest simulation |

Interactive API reference: <http://localhost:8000/docs>.

## Render deployment

The root `render.yaml` defines a Python API Web Service, a React/Vite Static Site, and a PostgreSQL database. Deployment is manual through your Render account; creating the Blueprint does not deploy anything until you connect and apply it.

### Prepare the GitHub repository

1. Review the project and confirm that `.env` files, API keys, database files, virtual environments, and trained model artifacts are not staged. `.gitignore` excludes local state and environment files.
2. Push the project root (including `render.yaml`) to a GitHub repository.
3. In Render, choose **New + → Blueprint**, connect the repository, and select the branch containing `render.yaml`.
4. Review the services and environment values before applying the Blueprint. Do not commit credentials or paste database URLs into Git.

### Blueprint service settings

| Service | Type / root | Build command | Start / publish |
|---|---|---|---|
| `ecopulse-api` | Web Service / `backend` | `pip install -r requirements.txt` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `ecopulse-frontend` | Static Site / `frontend` | `npm install && npm run build` | Publish directory: `dist` |
| `ecopulse-db` | PostgreSQL | Managed by Render | Database connection is injected as `DATABASE_URL` |

The static site includes a catch-all rewrite to `/index.html` so the app loads on refresh. The frontend build receives the API and secure WebSocket URLs as build-time variables. If you rename services or use a custom domain, update those URLs and backend CORS origins, then redeploy the frontend.

### Environment variables

Configure these on Render (the Blueprint provides defaults where safe):

| Variable | Service | Value |
|---|---|---|
| `DATABASE_URL` | Backend | Automatically linked PostgreSQL connection string; keep it private |
| `CORS_ORIGINS` | Backend | Exact deployed frontend origin, e.g. `https://ecopulse-frontend.onrender.com` |
| `WEATHER_LATITUDE` | Backend | Optional latitude for the location you choose |
| `WEATHER_LONGITUDE` | Backend | Optional longitude for the location you choose |
| `WEATHER_TIMEZONE` | Backend | IANA timezone for that location, e.g. `America/Los_Angeles` |
| `VITE_API_BASE_URL` | Frontend | `https://ecopulse-api.onrender.com/api/v1` |
| `VITE_WS_URL` | Frontend | `wss://ecopulse-api.onrender.com/ws/grid-telemetry` |

`WEATHER_LATITUDE` and `WEATHER_LONGITUDE` may be left blank; the app then labels and uses synthetic weather. Do not configure production `DATABASE_URL` as SQLite: Render web-service storage is ephemeral. On startup SQLAlchemy creates tables automatically and writes simulations, configuration, model metadata, and credits to PostgreSQL.

### PostgreSQL and free-tier limitations

Use the Blueprint-linked `DATABASE_URL` and keep the database and backend in the same Render region. EcoPulse accepts SQLite locally and normalizes PostgreSQL URLs to the psycopg 3 driver without connecting during module import.

Render currently offers free Static Sites, Web Services, and Postgres databases for experimentation. Free Web Services spin down after 15 minutes without inbound traffic and typically take about a minute to wake. Their filesystem is ephemeral, so local SQLite data and model files are not durable there; the PostgreSQL service is required for simulation persistence. Free Render Postgres has a fixed 1 GB limit, expires 30 days after creation, has no backups, and is deleted after its 14-day post-expiry grace period unless upgraded. Free services are not recommended for production. See Render's current [free instance limitations](https://render.com/docs/free) before choosing a plan.

### WebSocket, health, and model behavior

The frontend uses `wss://` for the deployed `/ws/grid-telemetry` endpoint. A WebSocket failure falls back to REST dashboard polling. Verify the backend at `https://<backend-name>.onrender.com/api/v1/health` and the API docs at `/docs`. Free backend spin-down can delay the first request and WebSocket connection. Model artifacts are stored on the service filesystem and therefore may be retrained at startup after a fresh deploy or restart; trained models are reused for subsequent requests in that process.

## Tests and build

Backend tests:

```powershell
cd .\backend
.\.venv\Scripts\Activate.ps1
pytest -q
python -m pip check
```

Frontend production build and dependency audit:

```powershell
cd .\frontend
npm run build
npm audit
```

## Troubleshooting

- **Render health check fails:** Confirm the backend start command uses `0.0.0.0` and `$PORT`; inspect Render logs for environment, dependency, or database errors.
- **Database connection fails:** Confirm `DATABASE_URL` is linked to the active PostgreSQL service and both services use the same region. Do not expose the connection string in source control or public logs.
- **CORS errors:** Set `CORS_ORIGINS` to the exact frontend origin (scheme and hostname, no path), then redeploy the backend.
- **Frontend calls localhost or API requests fail:** Set `VITE_API_BASE_URL` and `VITE_WS_URL` on the static site and trigger a new frontend build. These values are compiled into the static bundle.
- **WebSocket does not connect:** Check the backend service status and `wss://` URL. The UI polls the REST dashboard while reconnecting.
- **Synthetic weather appears:** Set valid coordinates and an IANA `WEATHER_TIMEZONE`, then wait for the failure cache to expire (up to one minute) or restart the backend. Weather API errors automatically fall back.
- **Local PowerShell blocks activation:** Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate `.venv`; or invoke `.venv\Scripts\python.exe` directly.
- **Forecast page lacks model scores:** Call `POST /api/v1/model/train`; this saves training metadata used by the forecast page.


## Live Demo
Experience EcoPulse live: [Open EcoPulse Dashboard](https://ecopulse-frontend-p55z.onrender.com/)
