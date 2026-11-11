import { BatteryCharging, Coins, Zap } from "lucide-react";
import MetricCard from "../components/MetricCard";

const illustrativeCredits = {
  total_credits: 420,
  household_credits: [
    { household_id: "Sample household A", energy_kwh: 18, credits: 180 },
    { household_id: "Sample household B", energy_kwh: 12, credits: 120 },
    { household_id: "Sample household C", energy_kwh: 12, credits: 120 },
  ],
  transactions: [
    {
      id: "demo-1",
      timestamp: "2026-11-09T10:30:00Z",
      household_id: "Sample household A",
      energy_kwh: 18,
      credits: 180,
      simulation_id: 101,
    },
    {
      id: "demo-2",
      timestamp: "2026-11-09T11:15:00Z",
      household_id: "Sample household B",
      energy_kwh: 12,
      credits: 120,
      simulation_id: 101,
    },
    {
      id: "demo-3",
      timestamp: "2026-11-10T09:45:00Z",
      household_id: "Sample household C",
      energy_kwh: 12,
      credits: 120,
      simulation_id: 102,
    },
  ],
  energy_bank: {
    capacity_kwh: 320,
    stored_energy_kwh: 176,
    state_of_charge_percent: 55,
    energy_discharged_kwh: 32,
    community_contribution_kwh: 42,
  },
  notice: "Illustrative figures only; no real energy assets, payments, or household records are represented.",
};

export default function Credits({ credits, loading, error, publicDemoMode }) {
  const displayedCredits = publicDemoMode ? illustrativeCredits : credits;
  const households = displayedCredits?.household_credits || [];
  const transactions = displayedCredits?.transactions || [];
  const bank = displayedCredits?.energy_bank;
  if (!displayedCredits) {
    return (
      <div className="page-stack">
        <div className="page-heading">
          <div><h1>Community Energy Bank</h1><p>Virtual storage and simulated household micro-credit allocations.</p></div>
          <span className="simulated-pill"><span /> Simulation only</span>
        </div>
        <div className={error ? "error-banner" : "empty-panel"} role={error ? "alert" : undefined}>
          {error || (loading ? "Loading the community energy bank…" : "Community bank data is unavailable.")}
        </div>
      </div>
    );
  }
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Community Energy Bank</h1>
          <p>Virtual storage state and simulated household micro-credit allocations.</p>
        </div>
        <span className="simulated-pill"><span /> Virtual · simulated</span>
      </div>
      {publicDemoMode && (
        <div className="notice" role="note">
          <strong>PUBLIC DEMO — ILLUSTRATIVE DATA</strong>
          <p>These fictional examples are not actual household records, credit balances, or transaction history.</p>
        </div>
      )}
      {error && <div className="error-banner" role="alert">{error} Showing the last available bank data.</div>}
      <div className="metric-grid bank-metrics">
        <MetricCard label="Virtual storage capacity" value={bank?.capacity_kwh ?? "—"} unit="kWh" icon={BatteryCharging} detail="Abstract simulated storage" tone="amber" />
        <MetricCard label="Stored energy" value={bank?.stored_energy_kwh ?? "—"} unit="kWh" icon={BatteryCharging} detail={`${bank?.state_of_charge_percent ?? "—"}% state of charge`} tone="amber" />
        <MetricCard label="Energy discharged" value={bank?.energy_discharged_kwh ?? "—"} unit="kWh" icon={Zap} detail="Latest simulation" tone="blue" />
        <MetricCard label="Community contribution" value={bank?.community_contribution_kwh ?? "—"} unit="kWh" icon={Zap} detail="Stored or exported qualifying energy" />
        <MetricCard label="Simulated micro-credits" value={displayedCredits.total_credits ?? "—"} unit="credits" icon={Coins} detail="Allocated from validated contribution records" tone="amber" />
      </div>
      <div className="two-column">
        <section className="panel">
          <div className="panel-heading"><div><h2>Household contribution history</h2><p>Simulated equal-share allocation; no household-level metering</p></div></div>
          {households.length ? <div className="household-list">
            {households.map((household) => <div className="household-row" key={household.household_id}>
              <span>{household.household_id}<small>{household.energy_kwh} kWh contributed</small></span><strong>{household.credits.toLocaleString()} simulated credits</strong>
              <div className="credit-bar"><span style={{ width: `${Math.min(100, household.credits / Math.max(...households.map((item) => item.credits), 1) * 100)}%` }} /></div>
            </div>)}
          </div> : <div className="empty-state">No credit transactions yet. Run a simulation with renewable surplus.</div>}
          {publicDemoMode && (
            <div className="notice">
              <strong>Illustrative incentive:</strong> 10 simulated credits per qualifying community-contribution kWh. This example rate has no cash value.
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading"><div><h2>Recent micro-credit allocations</h2><p>Validated simulated transaction ledger</p></div></div>
          {transactions.length ? <div className="table-scroll">
            <table><thead><tr><th>Household</th><th>Contribution</th><th>Credits</th><th>Simulation</th><th>Time</th></tr></thead>
              <tbody>{transactions.slice(0, 16).map((transaction) => <tr key={transaction.id}>
                <td>{transaction.household_id}</td><td>{transaction.energy_kwh} kWh</td><td>{transaction.credits}</td><td>#{transaction.simulation_id}</td><td>{new Date(transaction.timestamp).toLocaleString()}</td>
              </tr>)}</tbody>
            </table>
          </div> : <div className="empty-state">No transactions recorded yet.</div>}
        </section>
      </div>
      <div className="notice">{displayedCredits.notice || "Virtual storage and simulated credits only; not real assets or payments."}{displayedCredits.excluded_transactions ? ` ${displayedCredits.excluded_transactions} invalid or duplicate ledger rows were excluded.` : ""}</div>
    </div>
  );
}
