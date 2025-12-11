'use client';

import { useEffect, useState } from 'react';
import { usePortfolio } from '@/hooks/useApi';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface DataPoint {
  timestamp: Date;
  equity: number;
}

export default function EquityChart() {
  const { data: portfolio } = usePortfolio();
  const [dataPoints, setDataPoints] = useState<DataPoint[]>([]);

  // Add new data point when portfolio changes
  useEffect(() => {
    if (portfolio?.total_equity) {
      setDataPoints(prev => {
        const newPoint = {
          timestamp: new Date(),
          equity: portfolio.total_equity
        };
        // Keep last 100 points
        const updated = [...prev, newPoint].slice(-100);
        return updated;
      });
    }
  }, [portfolio?.total_equity]);

  // Initialize with starting data
  useEffect(() => {
    if (dataPoints.length === 0 && portfolio?.total_equity) {
      // Create initial synthetic data for demo
      const initialEquity = 10000;
      const now = Date.now();
      const points: DataPoint[] = [];
      for (let i = 24; i >= 0; i--) {
        const variance = (Math.random() - 0.5) * 200;
        points.push({
          timestamp: new Date(now - i * 3600000),
          equity: initialEquity + variance + (24 - i) * 10
        });
      }
      points.push({ timestamp: new Date(), equity: portfolio.total_equity });
      setDataPoints(points);
    }
  }, [portfolio?.total_equity, dataPoints.length]);

  if (dataPoints.length < 2) {
    return (
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Equity Curve</h3>
        </div>
        <div className="h-64 flex items-center justify-center text-[#8b8d93]">
          Loading chart data...
        </div>
      </div>
    );
  }

  const minEquity = Math.min(...dataPoints.map(d => d.equity));
  const maxEquity = Math.max(...dataPoints.map(d => d.equity));
  const range = maxEquity - minEquity || 1;
  const padding = range * 0.1;

  const chartHeight = 200;
  const chartWidth = 100; // percentage

  // Generate SVG path
  const points = dataPoints.map((d, i) => {
    const x = (i / (dataPoints.length - 1)) * 100;
    const y = chartHeight - ((d.equity - minEquity + padding) / (range + padding * 2)) * chartHeight;
    return `${x},${y}`;
  });

  const linePath = `M ${points.join(' L ')}`;
  const areaPath = `${linePath} L 100,${chartHeight} L 0,${chartHeight} Z`;

  const startEquity = dataPoints[0].equity;
  const currentEquity = dataPoints[dataPoints.length - 1].equity;
  const change = currentEquity - startEquity;
  const changePercent = (change / startEquity) * 100;
  const isPositive = change >= 0;

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">Equity Curve</h3>
          <p className="text-sm text-[#8b8d93]">Last 24 hours</p>
        </div>
        <div className="text-right">
          <p className={`text-lg font-semibold flex items-center gap-1 ${
            isPositive ? 'text-[#00c853]' : 'text-[#ff4757]'
          }`}>
            {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {isPositive ? '+' : ''}{changePercent.toFixed(2)}%
          </p>
          <p className="text-sm text-[#8b8d93]">
            {isPositive ? '+' : ''}${change.toFixed(2)}
          </p>
        </div>
      </div>

      {/* Chart */}
      <div className="relative h-64">
        <svg
          viewBox={`0 0 100 ${chartHeight}`}
          className="w-full h-full"
          preserveAspectRatio="none"
        >
          {/* Gradient */}
          <defs>
            <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor={isPositive ? '#00c853' : '#ff4757'}
                stopOpacity="0.3"
              />
              <stop
                offset="100%"
                stopColor={isPositive ? '#00c853' : '#ff4757'}
                stopOpacity="0"
              />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 25, 50, 75, 100].map((y) => (
            <line
              key={y}
              x1="0"
              y1={(y / 100) * chartHeight}
              x2="100"
              y2={(y / 100) * chartHeight}
              stroke="#2a2d35"
              strokeWidth="0.5"
            />
          ))}

          {/* Area */}
          <path
            d={areaPath}
            fill="url(#equityGradient)"
          />

          {/* Line */}
          <path
            d={linePath}
            fill="none"
            stroke={isPositive ? '#00c853' : '#ff4757'}
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />

          {/* Current point */}
          <circle
            cx="100"
            cy={chartHeight - ((currentEquity - minEquity + padding) / (range + padding * 2)) * chartHeight}
            r="3"
            fill={isPositive ? '#00c853' : '#ff4757'}
            className="animate-pulse"
          />
        </svg>

        {/* Y-axis labels */}
        <div className="absolute top-0 right-0 h-full flex flex-col justify-between text-xs text-[#8b8d93] py-2">
          <span>${(maxEquity + padding).toFixed(0)}</span>
          <span>${((maxEquity + minEquity) / 2).toFixed(0)}</span>
          <span>${(minEquity - padding).toFixed(0)}</span>
        </div>
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between text-xs text-[#8b8d93] mt-2 px-2">
        <span>24h ago</span>
        <span>12h ago</span>
        <span>Now</span>
      </div>
    </div>
  );
}
