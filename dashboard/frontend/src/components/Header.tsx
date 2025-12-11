'use client';

import { useState, useEffect } from 'react';
import { Status, startBot, stopBot, runCycle } from '@/lib/api';
import { usePortfolio } from '@/hooks/useApi';
import { Play, Square, RefreshCw, TrendingUp, TrendingDown, Clock, Hash } from 'lucide-react';
import { mutate } from 'swr';

interface HeaderProps {
  status?: Status;
}

export default function Header({ status }: HeaderProps) {
  const [loading, setLoading] = useState(false);
  const [countdown, setCountdown] = useState<number>(0);
  const [elapsed, setElapsed] = useState<number>(0);
  const { data: portfolio } = usePortfolio();

  // Timer effect - 카운트다운 (자동 실행시) 또는 경과 시간 (수동시)
  useEffect(() => {
    if (!status?.last_run) {
      setCountdown(0);
      setElapsed(0);
      return;
    }

    const intervalMinutes = status.interval_minutes ?? 15;
    // 서버는 UTC 시간을 반환하므로 'Z'를 붙여서 UTC로 파싱
    const lastRunStr = status.last_run.endsWith('Z') ? status.last_run : status.last_run + 'Z';
    const lastRun = new Date(lastRunStr).getTime();
    const nextRun = lastRun + intervalMinutes * 60 * 1000;

    const updateTimer = () => {
      const now = Date.now();
      const remaining = Math.max(0, Math.floor((nextRun - now) / 1000));
      const elapsedTime = Math.floor((now - lastRun) / 1000);
      setCountdown(remaining);
      setElapsed(elapsedTime);
    };

    updateTimer();
    const timer = setInterval(updateTimer, 1000);
    return () => clearInterval(timer);
  }, [status?.last_run, status?.interval_minutes]);

  const formatCountdown = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleStart = async () => {
    setLoading(true);
    try {
      await startBot();
      mutate('status');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopBot();
      mutate('status');
    } finally {
      setLoading(false);
    }
  };

  const handleRunCycle = async () => {
    setLoading(true);
    try {
      await runCycle();
      mutate('status');
      mutate('portfolio');
      mutate('positions');
    } finally {
      setLoading(false);
    }
  };

  const isRunning = status?.running ?? false;
  const totalEquity = portfolio?.total_equity ?? 1000;
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const dailyPnlPct = totalEquity > 0 ? (dailyPnl / totalEquity) * 100 : 0;

  return (
    <nav className="sticky top-0 z-50 border-b-2 border-gray-300 bg-white">
      <div className="mx-auto max-w-[95vw] px-2">
        <div className="flex h-14 items-center justify-between">
          {/* Logo */}
          <div className="flex items-center">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-600 to-purple-600 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-white" />
              </div>
              <span className="text-lg font-bold text-black">Prediction Market Bot</span>
            </div>
          </div>

          {/* Center - Portfolio Stats */}
          <div className="hidden md:flex items-center gap-8">
            <div className="flex flex-col items-center">
              <span className="text-[10px] text-gray-500 uppercase tracking-wide">Total Equity</span>
              <span className="text-lg font-bold font-mono">${totalEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </div>
            <div className="w-px h-8 bg-gray-300" />
            <div className="flex flex-col items-center">
              <span className="text-[10px] text-gray-500 uppercase tracking-wide">Daily P&L</span>
              <div className={`flex items-center gap-1 text-lg font-bold font-mono ${dailyPnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {dailyPnl >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                <span>{dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}</span>
                <span className="text-xs">({dailyPnlPct >= 0 ? '+' : ''}{dailyPnlPct.toFixed(2)}%)</span>
              </div>
            </div>
            <div className="w-px h-8 bg-gray-300" />
            <div className="flex flex-col items-center">
              <span className="text-[10px] text-gray-500 uppercase tracking-wide">Positions</span>
              <span className="text-lg font-bold font-mono">{portfolio?.position_count ?? 0}</span>
            </div>
          </div>

          {/* Right - Controls */}
          <div className="flex items-center gap-3">
            {/* Cycle Info */}
            <div className="flex items-center gap-3 px-3 py-1.5 bg-gray-100 rounded-lg">
              {/* Cycle Count */}
              <div className="flex items-center gap-1">
                <Hash className="w-3.5 h-3.5 text-gray-500" />
                <span className="text-xs font-mono font-medium text-gray-700">
                  {status?.cycle_count ?? 0}
                </span>
              </div>

              {/* Timer - 자동 실행시 다음 사이클까지 카운트다운, 수동시 마지막 실행 후 경과 시간 */}
              {status?.last_run && (
                <>
                  <div className="w-px h-4 bg-gray-300" />
                  <div className="flex items-center gap-1">
                    <Clock className={`w-3.5 h-3.5 ${isRunning ? 'text-blue-500' : 'text-gray-400'}`} />
                    <span className={`text-xs font-mono font-medium ${isRunning ? 'text-blue-600' : 'text-gray-500'}`}>
                      {isRunning && countdown > 0
                        ? formatCountdown(countdown)
                        : isRunning
                        ? 'Running...'
                        : `+${formatCountdown(elapsed)}`
                      }
                    </span>
                  </div>
                </>
              )}

              {/* Status Indicator */}
              <div className="w-px h-4 bg-gray-300" />
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}`} />
                <span className="text-xs font-medium text-gray-700">
                  {isRunning ? 'Running' : 'Stopped'}
                </span>
              </div>
            </div>

            {/* Run Cycle Button */}
            <button
              onClick={handleRunCycle}
              disabled={loading || isRunning}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg text-xs font-medium hover:bg-blue-200 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Run Cycle
            </button>

            {/* Start/Stop Button - status 로딩 중일 때는 비활성화 */}
            {/* 모든 버튼에 w-[72px]를 적용하여 레이아웃 시프트 방지 */}
            {!status ? (
              <button
                disabled
                className="flex items-center justify-center gap-1.5 w-[72px] py-1.5 bg-gray-300 text-gray-500 rounded-lg text-xs font-medium opacity-50"
              >
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              </button>
            ) : isRunning ? (
              <button
                onClick={handleStop}
                disabled={loading}
                className="flex items-center justify-center gap-1.5 w-[72px] py-1.5 bg-red-600 text-white rounded-lg text-xs font-medium hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                <Square className="w-3.5 h-3.5" />
                Stop
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={loading}
                className="flex items-center justify-center gap-1.5 w-[72px] py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                <Play className="w-3.5 h-3.5" />
                Start
              </button>
            )}

            {/* Demo Badge */}
            {status?.demo_mode && (
              <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded text-[10px] font-bold uppercase">
                Demo
              </span>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
