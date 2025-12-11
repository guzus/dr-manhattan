'use client';

import { useStatus, usePortfolio } from '@/hooks/useApi';
import { Activity, TrendingUp, TrendingDown, Clock, Zap } from 'lucide-react';

export default function StatusCard() {
  const { data: status, error: statusError } = useStatus();
  const { data: portfolio, error: portfolioError } = usePortfolio();

  if (statusError || portfolioError) {
    return (
      <div className="bg-red-900/50 rounded-lg p-6">
        <p className="text-red-400">Failed to load status</p>
      </div>
    );
  }

  if (!status || !portfolio) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-10 bg-gray-700 rounded w-1/2"></div>
      </div>
    );
  }

  const pnlColor = portfolio.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400';
  const PnlIcon = portfolio.realized_pnl >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Total Equity */}
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <span className="text-gray-400 text-sm">Total Equity</span>
          <Activity className="w-5 h-5 text-blue-400" />
        </div>
        <p className="text-2xl font-bold mt-2">${portfolio.total_equity.toFixed(2)}</p>
        <p className={`text-sm mt-1 flex items-center ${pnlColor}`}>
          <PnlIcon className="w-4 h-4 mr-1" />
          {portfolio.realized_pnl >= 0 ? '+' : ''}${portfolio.realized_pnl.toFixed(2)}
        </p>
      </div>

      {/* Available Balance */}
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <span className="text-gray-400 text-sm">Available Balance</span>
          <Zap className="w-5 h-5 text-yellow-400" />
        </div>
        <p className="text-2xl font-bold mt-2">${portfolio.available_balance.toFixed(2)}</p>
        <p className="text-sm text-gray-400 mt-1">
          {portfolio.position_count} open positions
        </p>
      </div>

      {/* Daily PnL */}
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <span className="text-gray-400 text-sm">Daily PnL</span>
          {portfolio.daily_pnl >= 0 ? (
            <TrendingUp className="w-5 h-5 text-green-400" />
          ) : (
            <TrendingDown className="w-5 h-5 text-red-400" />
          )}
        </div>
        <p className={`text-2xl font-bold mt-2 ${portfolio.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {portfolio.daily_pnl >= 0 ? '+' : ''}${portfolio.daily_pnl.toFixed(2)}
        </p>
        <p className="text-sm text-gray-400 mt-1">
          Drawdown: {portfolio.drawdown_pct.toFixed(1)}%
        </p>
      </div>

      {/* Bot Status */}
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <span className="text-gray-400 text-sm">Bot Status</span>
          <Clock className="w-5 h-5 text-purple-400" />
        </div>
        <div className="flex items-center mt-2">
          <span className={`w-3 h-3 rounded-full mr-2 ${status.running ? 'bg-green-400 animate-pulse' : 'bg-gray-500'}`}></span>
          <p className="text-lg font-semibold">
            {status.running ? 'Running' : 'Stopped'}
          </p>
        </div>
        <p className="text-sm text-gray-400 mt-1">
          {status.cycle_count} cycles | {status.total_trades} trades
        </p>
      </div>
    </div>
  );
}
