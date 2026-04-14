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
              <th scope="col">Direction</th>
              <th scope="col">Pair</th>
              <th scope="col">Executed</th>
              <th scope="col" className="num">Price</th>
              <th scope="col" className="num">Qty</th>
              <th scope="col" className="num">Value</th>
              <th scope="col" className="num">Fee</th>
              <th scope="col" className="num">Slippage</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td>
                  <span className={`trade-side trade-side--${trade.direction}`}>
                    {trade.direction}
                  </span>
                </td>
                <td>{trade.pair}</td>
                <td>{formatDateTime(trade.executedAt)}</td>
                <td className="num">${trade.price.toFixed(2)}</td>
                <td className="num">{trade.quantity.toFixed(4)}</td>
                <td className="num">${trade.valueUsd.toFixed(2)}</td>
                <td className="num">{trade.feeUsd != null ? `$${trade.feeUsd.toFixed(2)}` : "—"}</td>
                <td className="num">{trade.slippageBps != null ? `${trade.slippageBps.toFixed(1)} bps` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
