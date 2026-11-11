# EcoPulse Local End-to-End Smoke Test Report

## Executive summary

**Overall: PASS, with one responsive defect fixed and re-tested.** The local application, its simulation comparison, external intelligence integrations, dashboard, forecast, carbon estimates, community bank, and digital twin were exercised without a reproducible backend or browser error. The only reproduced issue was horizontal overflow on the Community Energy Bank at 390px; a one-line CSS grid fix resolved it.

Testing was local only. No commit, push, merge, deployment, Render setting, credential, or database schema was changed.

## Environment and test isolation

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`; Swagger: `http://127.0.0.1:8000/docs`
- Backend process used `DATABASE_URL` for a dedicated temporary SQLite database containing the nine smoke-test simulation records.
- `backend/ecopulse.db` was not the smoke-test database. Its modification time changed between the initial and final observations (22:24 to 22:45); because this environment may be shared and the test requests used the separate temporary database, the cause of that timestamp change cannot be attributed here. The project database was not restored, overwritten, or deleted.
- The final Tavily UI check was performed after clearing a stale Playwright response interception; six live results then rendered.

## Test results

| Area | Status | Evidence |
|---|---|---|
| Backend test suite | **PASS** | `53 passed, 1 skipped`; one dependency deprecation warning |
| Frontend production build | **PASS** | `npm run build` succeeded; Vite reported the charts chunk is 566.11 kB (above its 500 kB advisory threshold) |
| Diff whitespace check | **PASS** | `git diff --check` |
| Responsive pages | **PASS** | 20 page/viewport combinations; no horizontal overflow after the fix |
| Frontend credential scan | **PASS** | 25 source/build files; no configured API-key literals or common key-pattern matches |
| API response credential scan | **PASS** | No configured API-key values found in checked API responses |
| Browser console/network | **PASS** | After removing test interceptions: 0 console errors, 0 uncaught page errors, 0 failed requests |
| Git/Render | **PASS** | No commit, push, merge, deployment, or Render interaction |

### Browser and responsive checks

All five main pages loaded at each viewport: Overview, Forecast, Digital Twin, Simulation, and Community Energy Bank.

| Viewport | Size | Result |
|---|---:|---|
| Desktop | 1440 × 900 | **PASS** |
| Laptop | 1366 × 768 | **PASS** |
| Tablet | 768 × 1024 | **PASS** |
| Mobile | 390 × 844 | **PASS** |

The Community Energy Bank originally expanded the page to 440px at the 390px viewport. Changing its mobile grid track from `1fr` to `minmax(0, 1fr)` fixed the min-content overflow. The page and all other tested pages then fit their viewport.

## Page-by-page results

- **Overview — PASS:** loaded after refresh; 10 KPI cards and 8 charts rendered; API and WebSocket indicators connected.
- **Simulation — PASS:** Normal, heavy clouds, high demand, grid outage, low solar, evening peak, solar surplus, and storage constraints each completed successfully.
- **Energy Intelligence Center — PASS:** live current weather and forecast loaded; Delhi location search returned a location; forecast reported no alerts. Six live Tavily research cards rendered with valid HTTP(S) source URLs, `target="_blank"`, and `rel="noreferrer"`.
- **AI Advisor — PASS:** a live Groq answer was received with weather, research-source, and simulation context. A controlled upstream HTTP 502 was also exercised in the UI; the error was shown safely and the dashboard remained usable. This was an induced UI error, not a live Groq outage.
- **Forecast — PASS:** 24 RandomForest forecast points and charts rendered; forecast values are labelled as estimates, not measured energy or dispatch control. The forecast response used its labelled synthetic-weather fallback because its forecast coordinates were unavailable.
- **Carbon — PASS:** estimated grid-related emissions and baseline comparison were visible with assumptions. Carbon data is embedded in dashboard/simulation responses; there is no separate carbon endpoint. These are simulated estimates, not verified real-world reductions.
- **Community Energy Bank — PASS:** virtual storage, simulated contributions/credits, household history, and ledger rendered. Values are simulation accounting units, not money or physical battery telemetry.
- **Digital Twin — PASS:** the simulated energy-flow view rendered with four flow nodes and did not claim a live physical-device connection.

## Simulation and accounting checks

All eight scenario requests returned successfully. For each baseline-versus-optimized pair:

- Both dispatch strategies used the same scenario inputs, duration, random seed, weather, demand, and storage configuration.
- Energy balance error was 0 kWh in the tested outputs; all inspected numerical values were finite.
- Storage remained within configured bounds and charge/discharge accounting was internally consistent.
- Grid imports and exports were not simultaneously counted; the grid-outage scenario had no grid flow.
- Carbon estimates tracked grid imports and did not count renewable generation or storage charge/discharge again as emissions reductions.

Dispatch remains simulated; external weather or forecast information is not presented as measured energy flow.

## API and integration results

| Endpoint/integration | Status | Observed result |
|---|---|---|
| `GET /api/v1/health`, `GET /docs` | **PASS** | HTTP 200; health reports database connectivity |
| `GET /api/v1/dashboard` | **PASS** | HTTP 200; includes metrics, series, baseline comparison, carbon impact, and weather fields |
| `POST /api/v1/simulate` | **PASS** | HTTP 200 for all eight tested scenarios |
| `GET /api/v1/forecast` | **PASS** | HTTP 200; 24 forecast points |
| Weather current / forecast / search / intelligence overview | **PASS** | HTTP 200; parsed responses; forecast and location search returned data |
| Tavily research | **PASS** | HTTP 200; six results with preserved `source_url`, `source_domain`, and publication-date fields when available |
| Groq Advisor | **PASS** | Live request succeeded; contextual request returned an answer |
| `GET /api/v1/credits`, history, config | **PASS** | HTTP 200; parsed expected response fields |
| `/ws/grid-telemetry` | **PASS** | WebSocket connected; telemetry is marked simulated |
| Separate carbon endpoint | **NOT IMPLEMENTED** | No standalone carbon route exists; carbon fields are part of dashboard and simulation responses |

## Logs, security, and limitations

- Backend request logs contained no API-key-pattern matches, `ERROR`, traceback, or SQLAlchemy failure indicators.
- Checked frontend source/build files and API JSON responses for configured key literals; no key exposure was found. Credentials were not printed or changed.
- No unexpected browser console errors, failed requests, CORS errors, invalid numerical values, or database exceptions were observed in the final run.
- Research URLs were checked for valid HTTP(S) form and safe link attributes; external destinations were not opened during this local-only test.
- Weather alerts were empty for the tested forecast; this is a valid provider response, not an alert-rendering failure.
- The frontend build emits a non-fatal large-chunk advisory for the chart bundle.
- Energy dispatch, carbon impact, the digital twin, and bank credits remain simulated; no physical devices, household meters, or grid controls were exercised.
- The observed project-database modification-time change could not be attributed in this shared environment; the QA backend was directed to the separate temporary database.

## Local changes made

- `frontend/src/index.css`: corrected the mobile Community Energy Bank grid track; verified by the 20 responsive checks.
- `reports/LOCAL_E2E_SMOKE_TEST_REPORT.md`: this report.

Other uncommitted project changes were preserved. The temporary smoke-test database and local servers are cleaned up after validation. Smoke-test requests did not target the project database, which was not restored or deleted; its modification-time observation is noted above.
