import type { Trade } from "../types/backtest";

type TradeListProps = {
  trades: Trade[];
};

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function TradeList({ trades }: TradeListProps) {
  if (trades.length === 0) {
    return <p className="backtest-panel__empty">No trades recorded.</p>;
  }

  return (
    <div className="trade-list">
      <h3 className="trade-list__title">Trade History</h3>
      <div className="trade-list__scroll">
        <table className="trade-table" role="table">
          <thead>
            <tr>
              <th scope="col">Side</th>
              <th scope="col">Entry</th>
              <th scope="col">Exit</th>
              <th scope="col" className="num">Entry Price</th>
              <th scope="col" className="num">Exit Price</th>
              <th scope="col" className="num">PnL</th>
              <th scope="col" className="num">PnL %</th>
              <th scope="col">Duration</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td>
                  <span className={`trade-side trade-side--${trade.side}`}>
                    {trade.side}
                  </span>
                </td>
                <td>{formatDateTime(trade.entryTime)}</td>
                <td>{formatDateTime(trade.exitTime)}</td>
                <td className="num">${trade.entryPrice.toFixed(2)}</td>
                <td className="num">${trade.exitPrice.toFixed(2)}</td>
                <td className={`num ${trade.pnl >= 0 ? "pnl--positive" : "pnl--negative"}`}>
                  ${trade.pnl.toFixed(2)}
                </td>
                <td className={`num ${trade.pnlPercent >= 0 ? "pnl--positive" : "pnl--negative"}`}>
                  {(trade.pnlPercent * 100).toFixed(2)}%
                </td>
                <td>{trade.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
