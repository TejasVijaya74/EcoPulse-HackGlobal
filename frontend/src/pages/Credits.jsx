import { Coins } from "lucide-react";
import MetricCard from "../components/MetricCard";

export default function Credits({ credits }) {
  const households = credits?.household_credits || [];
  const transactions = credits?.transactions || [];
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>Community credits</h1>
          <p>Simulated rewards for renewable energy stored or exported for community use.</p>
        </div>
        <span className="simulated-pill"><span /> Incentive simulation</span>
      </div>
      <MetricCard label="Total credits issued" value={credits?.total_credits ?? "—"} unit="credits" icon={Coins} detail="1 kWh qualifying contribution earns configured credits" />
      <div className="two-column">
        <section className="panel">
          <div className="panel-heading"><div><h2>Household distribution</h2><p>Credits aggregated from stored/exported contributions</p></div></div>
          {households.length ? <div className="household-list">
            {households.map((household) => <div className="household-row" key={household.household_id}>
              <span>{household.household_id}</span><strong>{household.credits.toLocaleString()} credits</strong>
              <div className="credit-bar"><span style={{ width: `${Math.min(100, household.credits / Math.max(...households.map((item) => item.credits), 1) * 100)}%` }} /></div>
            </div>)}
          </div> : <div className="empty-state">No credit transactions yet. Run a simulation with renewable surplus.</div>}
        </section>
        <section className="panel">
          <div className="panel-heading"><div><h2>Recent transactions</h2><p>Latest simulated credit ledger entries</p></div></div>
          {transactions.length ? <div className="table-scroll">
            <table><thead><tr><th>Household</th><th>Contribution</th><th>Credits</th><th>Time</th></tr></thead>
              <tbody>{transactions.slice(0, 16).map((transaction) => <tr key={transaction.id}>
                <td>{transaction.household_id}</td><td>{transaction.energy_kwh} kWh</td><td>{transaction.credits}</td><td>{new Date(transaction.timestamp).toLocaleString()}</td>
              </tr>)}</tbody>
            </table>
          </div> : <div className="empty-state">No transactions recorded yet.</div>}
        </section>
      </div>
      <div className="notice">{credits?.notice || "This is a simulation, not a real payment system."}</div>
    </div>
  );
}

