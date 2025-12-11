'use client';

import { useState } from 'react';
import { useStatus } from '@/hooks/useApi';
import Header from '@/components/Header';
import PerformanceChart from '@/components/PerformanceChart';
import PositionsTable from '@/components/PositionsTable';
import TradesTable from '@/components/TradesTable';
import DecisionsPanel from '@/components/DecisionsPanel';

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
  return (
    <div className="h-full overflow-auto p-4">
      <TradesTable limit={100} />
    </div>
  );
}
