'use client';

import { useAgentStats } from '@/hooks/useApi';
import { Bot, Cpu, DollarSign } from 'lucide-react';

const agentColors: Record<string, string> = {
  research: 'bg-blue-500',
  probability: 'bg-purple-500',
  sentiment: 'bg-pink-500',
  risk: 'bg-orange-500',
  execution: 'bg-green-500',
  arbiter: 'bg-yellow-500',
};

export default function AgentStats() {
  const { data: agents, error } = useAgentStats();

  if (error) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-4">Agent Statistics</h2>
        <p className="text-red-400">Failed to load agent stats</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Agent Statistics</h2>
        <Bot className="w-5 h-5 text-purple-400" />
      </div>

      {!agents ? (
        <div className="animate-pulse space-y-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-16 bg-gray-700 rounded"></div>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {agents.map((agent) => (
            <div key={agent.name} className="bg-gray-700/50 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center">
                  <span className={`w-3 h-3 rounded-full mr-2 ${agentColors[agent.type] || 'bg-gray-500'}`}></span>
                  <span className="font-medium capitalize">{agent.type}</span>
                </div>
                <span className="text-sm text-gray-400">{agent.total_calls} calls</span>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="flex items-center text-gray-400">
                  <Cpu className="w-4 h-4 mr-1" />
                  {agent.total_tokens_used.toLocaleString()} tokens
                </div>
                <div className="flex items-center text-gray-400">
                  <DollarSign className="w-4 h-4 mr-1" />
                  ${agent.total_cost.toFixed(4)}
                </div>
              </div>
            </div>
          ))}

          {/* Total */}
          <div className="border-t border-gray-600 pt-3 mt-3">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Total Cost</span>
              <span className="font-semibold">
                ${agents.reduce((sum, a) => sum + a.total_cost, 0).toFixed(4)}
              </span>
            </div>
            <div className="flex justify-between text-sm mt-1">
              <span className="text-gray-400">Total Tokens</span>
              <span className="font-semibold">
                {agents.reduce((sum, a) => sum + a.total_tokens_used, 0).toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
