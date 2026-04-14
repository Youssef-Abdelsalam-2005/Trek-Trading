import { Link } from "react-router-dom";

const PLACEHOLDER_EXPERIMENTS = [
  { id: "exp-1", name: "SOL Mean Reversion", status: "backtesting" },
  { id: "exp-2", name: "Momentum Breakout", status: "paper_trading" },
  { id: "exp-3", name: "VWAP Scalper", status: "draft" },
];

export default function Dashboard() {
  return (
    <main className="dashboard">
      <h1>Dashboard</h1>
      <section>
        <h2>Experiments</h2>
        {PLACEHOLDER_EXPERIMENTS.length === 0 ? (
          <p className="empty-state">No experiments yet. Create one to get started.</p>
        ) : (
          <ul className="experiment-list">
            {PLACEHOLDER_EXPERIMENTS.map((exp) => (
              <li key={exp.id} className="experiment-card">
                <Link to={`/experiments/${exp.id}`}>
                  <strong>{exp.name}</strong>
                  <span className={`status status--${exp.status}`}>{exp.status.replace("_", " ")}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
