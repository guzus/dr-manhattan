'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { useStatus } from '@/hooks/useApi';
import { Play, Square, RefreshCw, RotateCcw, Zap } from 'lucide-react';
import { setLatestDecisions } from './DecisionsPanel';

export default function ControlPanel() {
  const { data: status, mutate } = useStatus();
  const [loading, setLoading] = useState<string | null>(null);
  const [lastDecisions, setLastDecisions] = useState<any[]>([]);

  const handleAction = async (action: string) => {
    setLoading(action);
    try {
      switch (action) {
        case 'start':
          await api.startTrading();
          break;
        case 'stop':
          await api.stopTrading();
          break;
        case 'cycle':
          const decisions = await api.runCycle();
          setLastDecisions(decisions);
          setLatestDecisions(decisions);  // Update the global DecisionsPanel
          break;
        case 'reset':
          await api.resetDemo();
          break;
      }
      mutate();
    } catch (error) {
      console.error(`Failed to ${action}:`, error);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">Control Panel</h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <button
          onClick={() => handleAction('start')}
          disabled={loading !== null || status?.running}
          className="flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg py-3 px-4 transition-colors"
        >
          {loading === 'start' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Play className="w-4 h-4" />
          )}
          Start
        </button>

        <button
          onClick={() => handleAction('stop')}
          disabled={loading !== null || !status?.running}
          className="flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg py-3 px-4 transition-colors"
        >
          {loading === 'stop' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Square className="w-4 h-4" />
          )}
          Stop
        </button>

        <button
          onClick={() => handleAction('cycle')}
          disabled={loading !== null}
          className="flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg py-3 px-4 transition-colors"
        >
          {loading === 'cycle' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Zap className="w-4 h-4" />
          )}
          Run Cycle
        </button>

        <button
          onClick={() => handleAction('reset')}
          disabled={loading !== null}
          className="flex items-center justify-center gap-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-lg py-3 px-4 transition-colors"
        >
          {loading === 'reset' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <RotateCcw className="w-4 h-4" />
          )}
          Reset Demo
        </button>
      </div>

      {/* Last Cycle Results */}
      {lastDecisions.length > 0 && (
        <div className="border-t border-gray-700 pt-4">
          <h3 className="text-sm font-semibold text-gray-400 mb-3">Last Cycle Decisions</h3>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {lastDecisions.map((decision, index) => (
              <div key={index} className="bg-gray-700/50 rounded p-3 text-sm">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-xs">{decision.market_id.slice(0, 12)}...</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                    decision.decision.includes('BUY') ? 'bg-green-900 text-green-300' :
                    decision.decision.includes('SELL') ? 'bg-red-900 text-red-300' :
                    'bg-gray-600 text-gray-300'
                  }`}>
                    {decision.decision}
                  </span>
                </div>
                <div className="flex items-center justify-between text-gray-400">
                  <span>Confidence: {decision.confidence}</span>
                  <span>${decision.position_size_usd.toFixed(2)}</span>
                </div>
                {decision.reasoning && (
                  <p className="text-gray-500 text-xs mt-1 line-clamp-2">
                    {decision.reasoning}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
