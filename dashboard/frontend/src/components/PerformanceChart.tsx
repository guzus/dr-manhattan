'use client';

import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, AreaData, Time, AreaSeries } from 'lightweight-charts';
import { usePortfolio, useEquityHistory } from '@/hooks/useApi';

export default function PerformanceChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area', Time> | null>(null);
  const [timeRange, setTimeRange] = useState<'1D' | '1W' | '1M' | 'ALL'>('ALL');
  const { data: portfolio } = usePortfolio();
  const { data: equityHistory } = useEquityHistory();

  // Filter equity history by time range
  const filterByTimeRange = (data: typeof equityHistory) => {
    if (!data || data.length === 0) return [];

    const now = new Date();
    let cutoff: Date;

    switch (timeRange) {
      case '1D':
        cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        break;
      case '1W':
        cutoff = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        break;
      case '1M':
        cutoff = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        break;
      case 'ALL':
      default:
        return data;
    }

    return data.filter(h => new Date(h.timestamp) >= cutoff);
  };

  // Convert equity history to chart data
  const getChartData = (): AreaData<Time>[] => {
    if (!equityHistory || equityHistory.length === 0) {
      // No data yet - show empty state with initial balance
      const now = Date.now();
      return [{
        time: Math.floor(now / 1000) as Time,
        value: portfolio?.total_equity ?? 1000,
      }];
    }

    // Filter by time range and convert to chart format
    const filtered = filterByTimeRange(equityHistory);

    if (filtered.length === 0) {
      // If no data in range, show current equity
      return [{
        time: Math.floor(Date.now() / 1000) as Time,
        value: portfolio?.total_equity ?? 1000,
      }];
    }

    return filtered.map((h) => ({
      time: Math.floor(new Date(h.timestamp).getTime() / 1000) as Time,
      value: h.equity,
    }));
  };

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#333333',
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      rightPriceScale: {
        borderColor: '#e0e0e0',
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: '#e0e0e0',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: {
          color: '#758696',
          width: 1,
          style: 2,
          labelBackgroundColor: '#758696',
        },
        horzLine: {
          color: '#758696',
          width: 1,
          style: 2,
          labelBackgroundColor: '#758696',
        },
      },
    });

    chartRef.current = chart;

    // Add area series (v5 API)
    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: '#2563eb',
      topColor: 'rgba(37, 99, 235, 0.4)',
      bottomColor: 'rgba(37, 99, 235, 0.0)',
      lineWidth: 2,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    seriesRef.current = areaSeries;

    // Set initial data
    areaSeries.setData(getChartData());
    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Update data when equity history or time range changes
  useEffect(() => {
    if (seriesRef.current && equityHistory) {
      seriesRef.current.setData(getChartData());
      chartRef.current?.timeScale().fitContent();
    }
  }, [equityHistory, timeRange]);

  const totalEquity = portfolio?.total_equity ?? 1000;
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const pnlPct = totalEquity > 0 ? (dailyPnl / (totalEquity - dailyPnl)) * 100 : 0;
  const filteredData = filterByTimeRange(equityHistory);
  const dataPoints = filteredData?.length ?? 0;
  const totalDataPoints = equityHistory?.length ?? 0;

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Chart Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <div className="flex items-center gap-6">
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Account Value</div>
            <div className="text-2xl font-bold font-mono">
              ${totalEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`px-3 py-1 rounded ${dailyPnl >= 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            <span className="text-sm font-bold font-mono">
              {dailyPnl >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          </div>
          <div className="text-xs text-gray-400">
            {dataPoints} data points
          </div>
        </div>

        {/* Time Range Selector (for future filtering) */}
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          {(['1D', '1W', '1M', 'ALL'] as const).map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                timeRange === range
                  ? 'bg-white text-black shadow-sm'
                  : 'text-gray-600 hover:text-black'
              }`}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      {/* Chart Container */}
      <div ref={chartContainerRef} className="flex-1 min-h-0" />

      {/* Empty State Message */}
      {dataPoints <= 1 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center text-gray-400">
            <p className="text-sm">No trading data yet</p>
            <p className="text-xs">Run a cycle to start recording equity</p>
          </div>
        </div>
      )}
    </div>
  );
}
