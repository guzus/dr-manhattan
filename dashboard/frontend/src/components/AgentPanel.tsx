'use client';

import { useAgentStats } from '@/hooks/useApi';
import { Bot, Cpu, DollarSign, Activity, Zap } from 'lucide-react';

const agentConfig: Record<string, { color: string; icon: any; description: string }> = {
  research: {
    color: '#3b82f6',
    icon: Activity,
    description: 'News & data gathering'
  },
  probability: {
    color: '#8b5cf6',
    icon: Cpu,
    description: 'Probability estimation'
  },
  sentiment: {
    color: '#ec4899',
    icon: Activity,
    description: 'Market sentiment'
  },
  risk: {
    color: '#f59e0b',
    icon: Zap,
    description: 'Risk assessment'
  },
  execution: {
    color: '#00c853',
    icon: Zap,
    description: 'Trade execution'
  },
  arbiter: {
    color: '#06b6d4',
    icon: Bot,
    description: 'Final decision'
  },
};

export default function AgentPanel() {
  const { data: agents, error } = useAgentStats();

  if (error) {
    return (
      <div className="card p-5">
        <h3 className="text-lg font-semibold text-white mb-4">AI Agents</h3>
        <p className="text-[#ff4757] text-sm">Failed to load agent stats</p>
      </div>
    );
  }

  const totalCost = agents?.reduce((sum, a) => sum + a.total_cost, 0) ?? 0;
  const totalTokens = agents?.reduce((sum, a) => sum + a.total_tokens_used, 0) ?? 0;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">AI Agents</h3>
          <p className="text-xs text-[#8b8d93]">GPT-4o-mini powered</p>
        </div>
        <Bot className="w-5 h-5 text-[#8b5cf6]" />
      </div>

      {!agents ? (
        <div className="space-y-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-12 bg-[#1e2025] rounded-lg animate-pulse"></div>
          ))}
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {agents.map((agent) => {
              const config = agentConfig[agent.type] || { color: '#8b8d93', icon: Bot, description: '' };
              const Icon = config.icon;

              return (
                <div
                  key={agent.name}
                  className="flex items-center justify-between p-3 bg-[#1e2025] rounded-lg hover:bg-[#252830] transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: `${config.color}20` }}
                    >
                      <Icon className="w-4 h-4" style={{ color: config.color }} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white capitalize">{agent.type}</p>
                      <p className="text-xs text-[#8b8d93]">{config.description}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-white">{agent.total_calls} calls</p>
                    <p className="text-xs text-[#8b8d93]">${agent.total_cost.toFixed(4)}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Total Summary */}
          <div className="mt-4 pt-4 border-t border-[#2a2d35]">
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2">
                <DollarSign className="w-4 h-4 text-[#8b8d93]" />
                <span className="text-sm text-[#8b8d93]">Total Cost</span>
              </div>
              <span className="text-sm font-semibold text-white">${totalCost.toFixed(4)}</span>
            </div>
            <div className="flex justify-between items-center mt-2">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-[#8b8d93]" />
                <span className="text-sm text-[#8b8d93]">Total Tokens</span>
              </div>
              <span className="text-sm font-semibold text-white">{totalTokens.toLocaleString()}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
