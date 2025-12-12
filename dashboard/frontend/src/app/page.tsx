'use client';

import { useState } from 'react';
import { useStatus, usePortfolio, useTrades } from '@/hooks/useApi';
import Header from '@/components/Header';
import PerformanceChart from '@/components/PerformanceChart';
import PositionsTable from '@/components/PositionsTable';
import TradesTable from '@/components/TradesTable';
import DecisionsPanel from '@/components/DecisionsPanel';
import { TrendingUp, TrendingDown, DollarSign, PiggyBank } from 'lucide-react';

type TabType = 'live' | 'history';

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>('live');
  const { data: status } = useStatus();

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-white text-black">
      {/* Header */}
      <Header status={status} />

      {/* Tab Navigation - Alpha Arena Style */}
      <div className="border-b-2 border-gray-300 bg-white">
        <div className="max-w-[95vw] mx-auto px-2">
          <nav className="flex gap-6">
            <button
              onClick={() => setActiveTab('live')}
              className={`py-3 px-2 text-xs font-bold uppercase tracking-wide border-b-2 transition-colors ${
                activeTab === 'live'
                  ? 'border-black text-black'
                  : 'border-transparent text-gray-500 hover:text-black'
              }`}
            >
              Live
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`py-3 px-2 text-xs font-bold uppercase tracking-wide border-b-2 transition-colors ${
                activeTab === 'history'
                  ? 'border-black text-black'
                  : 'border-transparent text-gray-500 hover:text-black'
              }`}
            >
              History
            </button>
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'live' ? <LiveView /> : <HistoryView />}
      </main>
    </div>
  );
}

function LiveView() {
  return (
    <div className="h-full flex flex-col">
      {/* Chart + Decisions Panel */}
      <div className="flex-1 min-h-0 flex">
        {/* Left - Chart (70%) */}
        <div className="w-[70%] border-r-2 border-gray-300">
          <PerformanceChart />
        </div>

        {/* Right - AI Decisions Panel (30%) */}
        <div className="w-[30%] overflow-hidden">
          <DecisionsPanel />
        </div>
      </div>

      {/* Bottom - Positions Table */}
      <div className="border-t-2 border-gray-300 h-[280px] overflow-auto">
        <PositionsTable />
      </div>
    </div>
  );
}

function HistoryView() {
  const [historyTab, setHistoryTab] = useState<'daily' | 'recent'>('daily');
  const { data: portfolio } = usePortfolio();
  const { data: trades } = useTrades(100);

  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const realizedPnl = portfolio?.realized_pnl ?? 0;
  const unrealizedPnl = portfolio?.unrealized_pnl ?? 0;
  const totalEquity = portfolio?.total_equity ?? 1000;
  const initialBalance = 1000;
  const totalPnl = totalEquity - initialBalance;
  const totalPnlPct = (totalPnl / initialBalance) * 100;

  // Group trades by date for daily view with realized P&L calculation
  const tradesByDate = trades?.reduce((acc, trade) => {
    const date = new Date(trade.timestamp).toLocaleDateString();
    if (!acc[date]) {
      acc[date] = {
        trades: [],
        totalBuy: 0,
        totalSell: 0,
        realizedPnl: 0,
        // 마켓별 포지션 추적 (FIFO 방식)
        positions: {} as Record<string, { side: string; size: number; avgPrice: number }[]>
      };
    }
    acc[date].trades.push(trade);

    const total = trade.total || (trade.size * trade.price);
    const marketKey = `${trade.market_id}-${trade.outcome_side}`;

    if (trade.side === 'BUY') {
      acc[date].totalBuy += total;
      // BUY: 포지션 추가
      if (!acc[date].positions[marketKey]) {
        acc[date].positions[marketKey] = [];
      }
      acc[date].positions[marketKey].push({
        side: 'BUY',
        size: trade.size,
        avgPrice: trade.price
      });
    } else {
      acc[date].totalSell += total;
      // SELL: 기존 BUY 포지션과 매칭하여 실현손익 계산
      const positions = acc[date].positions[marketKey] || [];
      let remainingSize = trade.size;

      while (remainingSize > 0 && positions.length > 0) {
        const pos = positions[0];
        const matchSize = Math.min(remainingSize, pos.size);
        // 실현손익 = (SELL 가격 - BUY 가격) * 수량
        acc[date].realizedPnl += (trade.price - pos.avgPrice) * matchSize;

        pos.size -= matchSize;
        remainingSize -= matchSize;

        if (pos.size <= 0) {
          positions.shift();
        }
      }
    }
    return acc;
  }, {} as Record<string, {
    trades: typeof trades;
    totalBuy: number;
    totalSell: number;
    realizedPnl: number;
    positions: Record<string, { side: string; size: number; avgPrice: number }[]>;
  }>) ?? {};

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* P&L Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Daily P&L */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              dailyPnl >= 0 ? 'bg-green-100' : 'bg-red-100'
            }`}>
              {dailyPnl >= 0 ? (
                <TrendingUp className="w-4 h-4 text-green-600" />
              ) : (
                <TrendingDown className="w-4 h-4 text-red-600" />
              )}
            </div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Daily P&L</span>
          </div>
          <div className={`text-2xl font-bold font-mono ${
            dailyPnl >= 0 ? 'text-green-600' : 'text-red-600'
          }`}>
            {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
          </div>
          <div className="text-xs text-gray-400 mt-1">Today's performance</div>
        </div>

        {/* Realized P&L */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              realizedPnl >= 0 ? 'bg-green-100' : 'bg-red-100'
            }`}>
              <DollarSign className={`w-4 h-4 ${realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'}`} />
            </div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Realized P&L</span>
          </div>
          <div className={`text-2xl font-bold font-mono ${
            realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
          }`}>
            {realizedPnl >= 0 ? '+' : ''}${realizedPnl.toFixed(2)}
          </div>
          <div className="text-xs text-gray-400 mt-1">From closed positions</div>
        </div>

        {/* Unrealized P&L */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              unrealizedPnl >= 0 ? 'bg-blue-100' : 'bg-orange-100'
            }`}>
              <PiggyBank className={`w-4 h-4 ${unrealizedPnl >= 0 ? 'text-blue-600' : 'text-orange-600'}`} />
            </div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Unrealized P&L</span>
          </div>
          <div className={`text-2xl font-bold font-mono ${
            unrealizedPnl >= 0 ? 'text-blue-600' : 'text-orange-600'
          }`}>
            {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
          </div>
          <div className="text-xs text-gray-400 mt-1">From open positions</div>
        </div>

        {/* Total P&L */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              totalPnl >= 0 ? 'bg-purple-100' : 'bg-red-100'
            }`}>
              {totalPnl >= 0 ? (
                <TrendingUp className="w-4 h-4 text-purple-600" />
              ) : (
                <TrendingDown className="w-4 h-4 text-red-600" />
              )}
            </div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Total P&L</span>
          </div>
          <div className={`text-2xl font-bold font-mono ${
            totalPnl >= 0 ? 'text-purple-600' : 'text-red-600'
          }`}>
            {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
          </div>
          <div className={`text-xs mt-1 ${totalPnlPct >= 0 ? 'text-purple-500' : 'text-red-500'}`}>
            {totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}% all time
          </div>
        </div>
      </div>

      {/* Sub-tabs: Daily / Recent */}
      <div className="flex gap-2 border-b border-gray-200">
        <button
          onClick={() => setHistoryTab('daily')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            historyTab === 'daily'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-black'
          }`}
        >
          Daily Summary
        </button>
        <button
          onClick={() => setHistoryTab('recent')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            historyTab === 'recent'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-black'
          }`}
        >
          Recent Trades
        </button>
      </div>

      {/* Content based on sub-tab */}
      {historyTab === 'daily' ? (
        /* Daily P&L Summary - 날짜별 손익만 표시 */
        <div className="bg-white rounded-lg border border-gray-200">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium text-right">Trades</th>
                <th className="px-4 py-3 font-medium text-right">Buy</th>
                <th className="px-4 py-3 font-medium text-right">Sell</th>
                <th className="px-4 py-3 font-medium text-right">Realized P&L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {Object.entries(tradesByDate).length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                    No trades yet
                  </td>
                </tr>
              ) : (
                Object.entries(tradesByDate)
                  .sort(([a], [b]) => new Date(b).getTime() - new Date(a).getTime())
                  .map(([date, data]) => {
                    return (
                      <tr key={date} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-black">{date}</td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {data.trades?.length || 0}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-gray-600">
                          ${data.totalBuy.toFixed(2)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-gray-600">
                          ${data.totalSell.toFixed(2)}
                        </td>
                        <td className={`px-4 py-3 text-right font-mono font-bold ${
                          data.realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {data.realizedPnl >= 0 ? '+' : ''}${data.realizedPnl.toFixed(2)}
                        </td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </table>
        </div>
      ) : (
        /* Recent Trades - 개별 거래 목록 */
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="divide-y divide-gray-100">
            {!trades || trades.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">
                No trades yet
              </div>
            ) : (
              trades.map((trade) => (
                <div
                  key={trade.trade_id}
                  className="px-4 py-3 hover:bg-gray-50 flex items-center justify-between"
                >
                  <div className="flex-1">
                    <div className="text-xs text-gray-400">{trade.event_title}</div>
                    <div className="text-sm text-blue-600">→ {trade.market_question}</div>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                      trade.side === 'BUY' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                    }`}>
                      {trade.side} {trade.outcome_side}
                    </span>
                    <span className="font-mono text-gray-600">
                      {trade.size.toFixed(1)} @ ${trade.price.toFixed(3)}
                    </span>
                    <span className="font-mono font-medium">
                      ${(trade.total || trade.size * trade.price).toFixed(2)}
                    </span>
                    <span className="text-xs text-gray-400">
                      {new Date(trade.timestamp).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
