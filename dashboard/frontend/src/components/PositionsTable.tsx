'use client';

import { usePositions } from '@/hooks/useApi';
import { TrendingUp, TrendingDown, ExternalLink, Briefcase } from 'lucide-react';

export default function PositionsTable() {
  const { data: positions, error } = usePositions();

  if (error) {
    return (
      <div className="h-full flex items-center justify-center bg-white">
        <p className="text-red-500 text-sm">Failed to load positions</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-4 py-2 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-blue-600" />
          <h3 className="text-xs font-bold uppercase tracking-wide text-black">Open Positions</h3>
          {positions && (
            <span className="px-2 py-0.5 bg-gray-100 rounded text-xs font-medium text-gray-600">
              {positions.length}
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      {!positions ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="animate-pulse text-gray-400">Loading...</div>
        </div>
      ) : positions.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
          <Briefcase className="w-8 h-8 mb-2" />
          <p className="text-sm">No open positions</p>
          <p className="text-xs">Positions will appear here when trades are executed</p>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50 z-10">
              <tr className="text-left text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-2 font-medium">Market</th>
                <th className="px-4 py-2 font-medium">Event</th>
                <th className="px-4 py-2 font-medium">Position</th>
                <th className="px-4 py-2 font-medium text-right">Entry</th>
                <th className="px-4 py-2 font-medium text-right">Current</th>
                <th className="px-4 py-2 font-medium text-right">Size</th>
                <th className="px-4 py-2 font-medium text-right">P&L</th>
                <th className="px-4 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {positions.map((position) => {
                const currentValue = position.size * position.current_price;
                const pnl = position.unrealized_pnl;
                const pnlPct = position.unrealized_pnl_pct;
                const isPositive = pnl >= 0;

                // Generate Polymarket link from market_id
                const polymarketLink = `https://polymarket.com/event/${position.market_id}`;

                return (
                  <tr
                    key={`${position.market_id}-${position.outcome_side}`}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    {/* Market (Question) */}
                    <td className="px-4 py-3">
                      <span className="font-medium text-black line-clamp-2 max-w-[250px]">
                        {position.market_question || position.market_id.slice(0, 20) + '...'}
                      </span>
                    </td>

                    {/* Event Title */}
                    <td className="px-4 py-3">
                      <span className="text-gray-500 text-xs line-clamp-1 max-w-[150px]">
                        {position.event_title || '-'}
                      </span>
                    </td>

                    {/* Position (YES/NO) */}
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-bold ${
                        position.outcome_side === 'YES'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {position.outcome_side}
                      </span>
                    </td>

                    {/* Entry Price */}
                    <td className="px-4 py-3 text-right font-mono text-gray-600">
                      ${position.average_price.toFixed(2)}
                    </td>

                    {/* Current Price */}
                    <td className="px-4 py-3 text-right font-mono text-black">
                      ${position.current_price.toFixed(2)}
                    </td>

                    {/* Size (Value) */}
                    <td className="px-4 py-3 text-right font-mono text-black font-medium">
                      ${currentValue.toFixed(2)}
                    </td>

                    {/* P&L */}
                    <td className="px-4 py-3 text-right">
                      <div className={`flex items-center justify-end gap-1 font-mono font-medium ${
                        isPositive ? 'text-green-600' : 'text-red-600'
                      }`}>
                        {isPositive ? (
                          <TrendingUp className="w-3 h-3" />
                        ) : (
                          <TrendingDown className="w-3 h-3" />
                        )}
                        <span>{isPositive ? '+' : ''}{pnlPct.toFixed(1)}%</span>
                      </div>
                    </td>

                    {/* Link */}
                    <td className="px-4 py-3">
                      <a
                        href={polymarketLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 hover:bg-gray-100 rounded transition-colors inline-flex"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="w-3.5 h-3.5 text-gray-400 hover:text-blue-600" />
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
