'use client';

import { useTrades } from '@/hooks/useApi';
import { History, ArrowUpRight, ArrowDownRight, ExternalLink } from 'lucide-react';

interface TradesTableProps {
  limit?: number;
}

export default function TradesTable({ limit = 50 }: TradesTableProps) {
  const { data: trades, error } = useTrades(limit);

  if (error) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-8">
        <h3 className="text-lg font-bold text-black mb-4">Trade History</h3>
        <p className="text-red-500 text-sm">Failed to load trades</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-purple-600" />
          <h3 className="text-sm font-bold uppercase tracking-wide text-black">Trade History</h3>
          {trades && (
            <span className="px-2 py-0.5 bg-gray-100 rounded text-xs font-medium text-gray-600">
              {trades.length} trades
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      {!trades ? (
        <div className="p-8 text-center">
          <div className="animate-pulse text-gray-400">Loading...</div>
        </div>
      ) : trades.length === 0 ? (
        <div className="py-16 text-center">
          <History className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">No trades yet</p>
          <p className="text-xs text-gray-400 mt-1">Your trade history will appear here</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-gray-500 text-xs uppercase tracking-wide">
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">Event / Selection</th>
                <th className="px-4 py-3 font-medium">Action</th>
                <th className="px-4 py-3 font-medium text-right">Size</th>
                <th className="px-4 py-3 font-medium text-right">Price</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {trades.map((trade) => {
                const isBuy = trade.side === 'BUY';
                const total = trade.total || trade.size * trade.price;

                // Generate Polymarket link using slug
                const polymarketLink = trade.slug
                  ? `https://polymarket.com/market/${trade.slug}`
                  : `https://polymarket.com/markets?search=${encodeURIComponent(trade.market_question?.slice(0, 30) || '')}`;

                return (
                  <tr
                    key={trade.trade_id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    {/* Time */}
                    <td className="px-4 py-3">
                      <div className="text-sm text-black">
                        {new Date(trade.timestamp).toLocaleDateString()}
                      </div>
                      <div className="text-xs text-gray-400">
                        {new Date(trade.timestamp).toLocaleTimeString()}
                      </div>
                    </td>

                    {/* Event + Selection (2줄 구조) */}
                    <td className="px-4 py-3 max-w-[280px]">
                      {/* Event Title (상위) */}
                      <div className="text-xs text-gray-500 mb-0.5 truncate">
                        {trade.event_title || 'Unknown Event'}
                      </div>
                      {/* Market Question (선택한 항목) */}
                      <a
                        href={polymarketLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-blue-600 hover:text-blue-800 hover:underline line-clamp-1 block"
                      >
                        → {trade.market_question || `Market ${trade.market_id.slice(0, 8)}...`}
                      </a>
                    </td>

                    {/* Action */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className={`w-6 h-6 rounded-full flex items-center justify-center ${
                          isBuy ? 'bg-green-100' : 'bg-red-100'
                        }`}>
                          {isBuy ? (
                            <ArrowUpRight className="w-3 h-3 text-green-600" />
                          ) : (
                            <ArrowDownRight className="w-3 h-3 text-red-600" />
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          <span className={`text-sm font-bold ${
                            isBuy ? 'text-green-600' : 'text-red-600'
                          }`}>
                            {trade.side}
                          </span>
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            trade.outcome_side === 'YES'
                              ? 'bg-green-100 text-green-700'
                              : 'bg-red-100 text-red-700'
                          }`}>
                            {trade.outcome_side}
                          </span>
                        </div>
                      </div>
                    </td>

                    {/* Size */}
                    <td className="px-4 py-3 text-right font-mono text-black">
                      {trade.size.toFixed(2)}
                    </td>

                    {/* Price */}
                    <td className="px-4 py-3 text-right font-mono text-gray-600">
                      ${trade.price.toFixed(3)}
                    </td>

                    {/* Total */}
                    <td className="px-4 py-3 text-right font-mono font-medium text-black">
                      ${total.toFixed(2)}
                    </td>

                    {/* Link */}
                    <td className="px-4 py-3">
                      <a
                        href={polymarketLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 hover:bg-gray-100 rounded transition-colors inline-flex"
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
