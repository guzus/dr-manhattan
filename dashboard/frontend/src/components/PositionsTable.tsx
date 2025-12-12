'use client';

import { usePositions } from '@/hooks/useApi';
import { TrendingUp, TrendingDown, Briefcase } from 'lucide-react';

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
                <th className="px-3 py-2 font-medium">Event / Selection</th>
                <th className="px-3 py-2 font-medium">Position</th>
                <th className="px-3 py-2 font-medium text-right">Entry Price</th>
                <th className="px-3 py-2 font-medium text-right">Shares</th>
                <th className="px-3 py-2 font-medium text-right">Entry Value</th>
                <th className="px-3 py-2 font-medium text-right">Current Price</th>
                <th className="px-3 py-2 font-medium text-right">Current Value</th>
                <th className="px-3 py-2 font-medium text-right">P&L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {positions.map((position) => {
                const pnl = position.unrealized_pnl;
                const pnlPct = position.unrealized_pnl_pct;
                const isPositive = pnl >= 0;

                // Generate Polymarket link using slug (uses /market/ which auto-redirects to correct page)
                const polymarketLink = position.slug
                  ? `https://polymarket.com/market/${position.slug}`
                  : `https://polymarket.com/markets?search=${encodeURIComponent(position.market_question?.slice(0, 30) || '')}`;

                return (
                  <tr
                    key={`${position.market_id}-${position.outcome_side}`}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    {/* Event + Selection (2줄 구조) */}
                    <td className="px-3 py-3 max-w-[280px]">
                      {/* Event Title (상위) */}
                      <div className="text-xs text-gray-500 mb-0.5 truncate">
                        {position.event_title || 'Unknown Event'}
                      </div>
                      {/* Market Question (선택한 항목) */}
                      <a
                        href={polymarketLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-blue-600 hover:text-blue-800 hover:underline line-clamp-1 block"
                      >
                        → {position.market_question || position.market_id.slice(0, 20) + '...'}
                      </a>
                    </td>

                    {/* Position (YES/NO) */}
                    <td className="px-3 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-bold ${
                        position.outcome_side === 'YES'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {position.outcome_side}
                      </span>
                    </td>

                    {/* Entry Price */}
                    <td className="px-3 py-3 text-right font-mono text-gray-600">
                      ${position.average_price.toFixed(3)}
                    </td>

                    {/* Shares */}
                    <td className="px-3 py-3 text-right font-mono text-black">
                      {position.size.toFixed(2)}
                    </td>

                    {/* Entry Value */}
                    <td className="px-3 py-3 text-right font-mono text-gray-600">
                      ${position.entry_value.toFixed(2)}
                    </td>

                    {/* Current Price */}
                    <td className="px-3 py-3 text-right font-mono text-black">
                      ${position.current_price.toFixed(3)}
                    </td>

                    {/* Current Value */}
                    <td className="px-3 py-3 text-right font-mono text-black font-medium">
                      ${position.current_value.toFixed(2)}
                    </td>

                    {/* P&L */}
                    <td className="px-3 py-3 text-right">
                      <div className={`flex flex-col items-end font-mono ${
                        isPositive ? 'text-green-600' : 'text-red-600'
                      }`}>
                        <div className="flex items-center gap-1 font-medium">
                          {isPositive ? (
                            <TrendingUp className="w-3 h-3" />
                          ) : (
                            <TrendingDown className="w-3 h-3" />
                          )}
                          <span>{isPositive ? '+' : ''}{pnlPct.toFixed(2)}%</span>
                        </div>
                        <span className="text-[10px]">
                          {isPositive ? '+' : ''}${pnl.toFixed(2)}
                        </span>
                      </div>
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
