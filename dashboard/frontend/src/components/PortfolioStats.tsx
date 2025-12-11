'use client';

import { TrendingUp, TrendingDown, DollarSign, PieChart, Activity } from 'lucide-react';

interface PortfolioStatsProps {
  portfolio: {
    total_equity: number;
    available_balance: number;
    realized_pnl: number;
    unrealized_pnl: number;
    daily_pnl: number;
    position_count: number;
    drawdown_pct: number;
  } | null | undefined;
}

export default function PortfolioStats({ portfolio }: PortfolioStatsProps) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="card p-5 animate-pulse">
            <div className="h-4 bg-[#2a2d35] rounded w-24 mb-3"></div>
            <div className="h-8 bg-[#2a2d35] rounded w-32"></div>
          </div>
        ))}
      </div>
    );
  }

  const totalPnl = portfolio.realized_pnl + portfolio.unrealized_pnl;
  const pnlPercent = portfolio.total_equity > 0
    ? (totalPnl / (portfolio.total_equity - totalPnl)) * 100
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {/* Total Equity */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[#8b8d93] text-sm">Total Equity</span>
          <DollarSign className="w-4 h-4 text-[#3b82f6]" />
        </div>
        <p className="text-2xl font-bold text-white">
          ${portfolio.total_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <p className={`text-sm mt-1 flex items-center gap-1 ${
          totalPnl >= 0 ? 'text-[#00c853]' : 'text-[#ff4757]'
        }`}>
          {totalPnl >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
          {totalPnl >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
        </p>
      </div>

      {/* Daily P&L */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[#8b8d93] text-sm">Daily P&L</span>
          <Activity className="w-4 h-4 text-[#8b5cf6]" />
        </div>
        <p className={`text-2xl font-bold ${
          portfolio.daily_pnl >= 0 ? 'text-[#00c853]' : 'text-[#ff4757]'
        }`}>
          {portfolio.daily_pnl >= 0 ? '+' : ''}${portfolio.daily_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <p className="text-sm text-[#8b8d93] mt-1">
          Drawdown: {portfolio.drawdown_pct.toFixed(1)}%
        </p>
      </div>

      {/* Available Balance */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[#8b8d93] text-sm">Available</span>
          <PieChart className="w-4 h-4 text-[#f59e0b]" />
        </div>
        <p className="text-2xl font-bold text-white">
          ${portfolio.available_balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <p className="text-sm text-[#8b8d93] mt-1">
          {portfolio.position_count} positions
        </p>
      </div>

      {/* Realized P&L */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[#8b8d93] text-sm">Realized P&L</span>
          {portfolio.realized_pnl >= 0 ? (
            <TrendingUp className="w-4 h-4 text-[#00c853]" />
          ) : (
            <TrendingDown className="w-4 h-4 text-[#ff4757]" />
          )}
        </div>
        <p className={`text-2xl font-bold ${
          portfolio.realized_pnl >= 0 ? 'text-[#00c853]' : 'text-[#ff4757]'
        }`}>
          {portfolio.realized_pnl >= 0 ? '+' : ''}${portfolio.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <p className="text-sm text-[#8b8d93] mt-1">
          Unrealized: {portfolio.unrealized_pnl >= 0 ? '+' : ''}${portfolio.unrealized_pnl.toFixed(2)}
        </p>
      </div>
    </div>
  );
}
