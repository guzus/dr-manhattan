'use client';

import { useState } from 'react';
import { useMarkets } from '@/hooks/useApi';
import { BarChart3, TrendingUp, Droplets, Globe, Trophy, Coins, Tv } from 'lucide-react';

const categories = [
  { id: 'all', label: 'All', icon: Globe },
  { id: 'politics', label: 'Politics', icon: Globe },
  { id: 'sports', label: 'Sports', icon: Trophy },
  { id: 'crypto', label: 'Crypto', icon: Coins },
  { id: 'entertainment', label: 'Entertainment', icon: Tv },
];

export default function MarketsList() {
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const { data: markets, error, isLoading } = useMarkets(
    selectedCategory === 'all' ? undefined : selectedCategory,
    10
  );

  if (error) {
    return (
      <div className="card p-5">
        <h3 className="text-lg font-semibold text-white mb-4">Markets</h3>
        <p className="text-[#ff4757] text-sm">Failed to load markets</p>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-[#f59e0b]" />
          <h3 className="text-lg font-semibold text-white">Markets</h3>
        </div>
      </div>

      {/* Category Tabs */}
      <div className="flex gap-1 mb-4 overflow-x-auto pb-2">
        {categories.map((cat) => {
          const Icon = cat.icon;
          return (
            <button
              key={cat.id}
              onClick={() => setSelectedCategory(cat.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                selectedCategory === cat.id
                  ? 'bg-[#3b82f6] text-white'
                  : 'bg-[#1e2025] text-[#8b8d93] hover:bg-[#252830] hover:text-white'
              }`}
            >
              <Icon className="w-3 h-3" />
              {cat.label}
            </button>
          );
        })}
      </div>

      {/* Markets List */}
      {!markets || isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-24 bg-[#1e2025] rounded-lg animate-pulse"></div>
          ))}
        </div>
      ) : markets.length === 0 ? (
        <div className="py-12 text-center">
          <BarChart3 className="w-12 h-12 text-[#2a2d35] mx-auto mb-3" />
          <p className="text-[#8b8d93]">No markets found</p>
          <p className="text-xs text-[#8b8d93] mt-1">Try selecting a different category</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[450px] overflow-y-auto pr-1">
          {markets.map((market) => {
            const yesPercent = market.yes_price * 100;

            return (
              <div
                key={market.id}
                className="p-4 bg-[#1e2025] rounded-lg hover:bg-[#252830] transition-all cursor-pointer group"
              >
                {/* Question */}
                <p className="text-sm text-white font-medium line-clamp-2 mb-3 group-hover:text-[#3b82f6] transition-colors">
                  {market.question}
                </p>

                {/* Price Bar */}
                <div className="mb-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-[#00c853] font-medium">YES {yesPercent.toFixed(0)}%</span>
                    <span className="text-[#ff4757] font-medium">NO {(100 - yesPercent).toFixed(0)}%</span>
                  </div>
                  <div className="h-2 bg-[#ff4757]/30 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#00c853] rounded-full transition-all"
                      style={{ width: `${yesPercent}%` }}
                    />
                  </div>
                </div>

                {/* Stats */}
                <div className="flex items-center justify-between text-xs text-[#8b8d93]">
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" />
                      ${market.volume_24h >= 1000 ? `${(market.volume_24h / 1000).toFixed(1)}K` : market.volume_24h.toFixed(0)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Droplets className="w-3 h-3" />
                      ${market.liquidity >= 1000 ? `${(market.liquidity / 1000).toFixed(1)}K` : market.liquidity.toFixed(0)}
                    </span>
                  </div>
                  {market.category && (
                    <span className="px-2 py-0.5 bg-[#2a2d35] rounded text-[10px] uppercase tracking-wide">
                      {market.category}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
