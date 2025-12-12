'use client';

import { useState, useEffect } from 'react';
import { Bot, TrendingUp, TrendingDown, ExternalLink, Clock } from 'lucide-react';
import { api } from '@/lib/api';

interface Decision {
  market_id: string;
  slug?: string;
  market_question?: string;
  decision: string;
  action?: string;
  side?: string;
  confidence: string;
  position_size_usd: number;
  reasoning: string;
  research_summary?: string;
  probability_assessment?: string;
  sentiment_analysis?: string;
  risk_assessment?: string;
  total_tokens: number;
  total_cost: number;
  timestamp: string;
}

// 글로벌 결정 저장소 (SWR 대신 간단한 상태 관리)
let latestDecisions: Decision[] = [];
let latestDecisionsVersion = 0;

export function setLatestDecisions(decisions: Decision[]) {
  latestDecisions = decisions;
  latestDecisionsVersion++;
}

export default function DecisionsPanel() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [currentVersion, setCurrentVersion] = useState(0);
  const [loading, setLoading] = useState(true);

  // Load decisions from API on mount
  useEffect(() => {
    const loadDecisions = async () => {
      try {
        const data = await api.getDecisions(50);
        if (data && data.length > 0) {
          setDecisions(data);
          latestDecisions = data;
          setLastUpdated(new Date());
        }
      } catch (error) {
        console.error('Failed to load decisions:', error);
      } finally {
        setLoading(false);
      }
    };

    loadDecisions();
  }, []);

  // Poll for new decisions from global state
  useEffect(() => {
    const checkDecisions = () => {
      if (latestDecisionsVersion > currentVersion && latestDecisions.length > 0) {
        setDecisions([...latestDecisions]);
        setCurrentVersion(latestDecisionsVersion);
        setLastUpdated(new Date());
      }
    };

    const interval = setInterval(checkDecisions, 500);
    return () => clearInterval(interval);
  }, [currentVersion]);

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-purple-600" />
            <h2 className="text-sm font-bold uppercase tracking-wide text-black">AI Analysis</h2>
          </div>
          {lastUpdated && (
            <div className="flex items-center gap-1 text-[10px] text-gray-400">
              <Clock className="w-3 h-3" />
              {formatTime(lastUpdated)}
            </div>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-0.5">Latest trading decisions</p>
      </div>

      {/* Decisions List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 px-4">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600 mb-2"></div>
            <p className="text-sm">Loading decisions...</p>
          </div>
        ) : decisions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 px-4">
            <Bot className="w-10 h-10 mb-2 opacity-50" />
            <p className="text-sm font-medium">No analysis yet</p>
            <p className="text-xs text-center mt-1">
              Click "Run Cycle" to analyze markets
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {decisions.map((decision, idx) => (
              <DecisionCard key={`${decision.market_id}-${idx}`} decision={decision} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionCard({ decision }: { decision: Decision }) {
  const [expanded, setExpanded] = useState(false);

  const isBuy = decision.decision.toUpperCase().includes('BUY');
  const isSell = decision.decision.toUpperCase().includes('SELL');
  const isHold = !isBuy && !isSell;

  // Parse confidence
  const confidence = decision.confidence?.toLowerCase() || 'low';
  const isHighConfidence = confidence === 'high';
  const isMediumConfidence = confidence === 'medium';

  // Polymarket link - prefer slug if available, then check if market_id is slug-like
  // /market/{slug} auto-redirects to the correct page
  const polymarketLink = decision.slug
    ? `https://polymarket.com/market/${decision.slug}`
    : `https://polymarket.com/markets?_s=${decision.market_id}`;

  // Display title: market_question or market_id
  const displayTitle = decision.market_question || `${decision.market_id.slice(0, 30)}...`;

  return (
    <div
      className="px-4 py-3 hover:bg-gray-50 cursor-pointer transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      {/* Main Info */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Decision Badge */}
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${
              isBuy
                ? 'bg-green-100 text-green-700'
                : isSell
                ? 'bg-red-100 text-red-700'
                : 'bg-gray-100 text-gray-700'
            }`}>
              {decision.decision}
            </span>
            {decision.side && (
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                decision.side === 'YES'
                  ? 'bg-green-100 text-green-700'
                  : 'bg-red-100 text-red-700'
              }`}>
                {decision.side}
              </span>
            )}
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              isHighConfidence
                ? 'bg-purple-100 text-purple-700'
                : isMediumConfidence
                ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-100 text-gray-500'
            }`}>
              {confidence}
            </span>
            {decision.position_size_usd > 0 && (
              <span className="text-xs text-gray-500 font-mono">
                ${decision.position_size_usd.toFixed(0)}
              </span>
            )}
          </div>

          {/* Market Question / ID */}
          <p className="text-xs text-gray-600 line-clamp-1" title={displayTitle}>
            {displayTitle}
          </p>
        </div>

        {/* Link */}
        <a
          href={polymarketLink}
          target="_blank"
          rel="noopener noreferrer"
          className="p-1.5 hover:bg-gray-100 rounded transition-colors"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink className="w-3.5 h-3.5 text-gray-400 hover:text-blue-600" />
        </a>
      </div>

      {/* Agent Analysis (Expanded) */}
      {expanded && (
        <div className="mt-2 space-y-2">
          {/* Research Summary */}
          {decision.research_summary && (
            <div className="p-2 bg-blue-50 rounded">
              <div className="text-[10px] font-bold text-blue-700 mb-1">Research</div>
              <div className="text-xs text-gray-600 leading-relaxed">
                {decision.research_summary}
              </div>
            </div>
          )}

          {/* Probability Assessment */}
          {decision.probability_assessment && (
            <div className="p-2 bg-green-50 rounded">
              <div className="text-[10px] font-bold text-green-700 mb-1">Probability</div>
              <div className="text-xs text-gray-600 font-mono">
                {decision.probability_assessment}
              </div>
            </div>
          )}

          {/* Sentiment Analysis */}
          {decision.sentiment_analysis && (
            <div className="p-2 bg-yellow-50 rounded">
              <div className="text-[10px] font-bold text-yellow-700 mb-1">Sentiment</div>
              <div className="text-xs text-gray-600 font-mono">
                {decision.sentiment_analysis}
              </div>
            </div>
          )}

          {/* Risk Assessment */}
          {decision.risk_assessment && (
            <div className="p-2 bg-red-50 rounded">
              <div className="text-[10px] font-bold text-red-700 mb-1">Risk</div>
              <div className="text-xs text-gray-600 font-mono">
                {decision.risk_assessment}
              </div>
            </div>
          )}

          {/* Arbiter Reasoning */}
          {decision.reasoning && (
            <div className="p-2 bg-purple-50 rounded">
              <div className="text-[10px] font-bold text-purple-700 mb-1">Final Decision</div>
              <div className="text-xs text-gray-600 leading-relaxed">
                {decision.reasoning}
              </div>
            </div>
          )}

          {/* Cost Info */}
          <div className="flex items-center gap-3 text-[10px] text-gray-400 pt-1">
            <span>{decision.total_tokens.toLocaleString()} tokens</span>
            <span>${decision.total_cost.toFixed(4)}</span>
            <span>{new Date(decision.timestamp).toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function formatTime(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);

  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  return date.toLocaleTimeString();
}
