import { useEffect, useRef, useState, useCallback } from 'react';
import useSWR from 'swr';
import { api, TradingWebSocket, Portfolio, Status, Position, EquityHistory } from '@/lib/api';

export function useStatus() {
  return useSWR('status', api.getStatus, {
    refreshInterval: 5000,
    revalidateOnFocus: false,
    keepPreviousData: true,
  });
}

export function usePortfolio() {
  return useSWR('portfolio', api.getPortfolio, { refreshInterval: 5000 });
}

export function usePositions() {
  return useSWR('positions', api.getPositions, { refreshInterval: 5000 });
}

export function useTrades(limit = 50) {
  return useSWR(['trades', limit], () => api.getTrades(limit), { refreshInterval: 10000 });
}

export function useMarkets(category?: string, limit = 20) {
  return useSWR(['markets', category, limit], () => api.getMarkets(category, limit), {
    refreshInterval: 30000,
  });
}

export function useAgentStats() {
  return useSWR('agents', api.getAgentStats, { refreshInterval: 10000 });
}

export function useEquityHistory() {
  return useSWR('equity-history', api.getEquityHistory, { refreshInterval: 10000 });
}

// WebSocket-based real-time hook
export function useWebSocket(topics: string[] = ['all']) {
  const wsRef = useRef<TradingWebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [portfolio, setPortfolio] = useState<Partial<Portfolio> | null>(null);
  const [status, setStatus] = useState<Partial<Status> | null>(null);
  const [latestEquity, setLatestEquity] = useState<{ timestamp: string; equity: number } | null>(null);
  const [latestDecision, setLatestDecision] = useState<any | null>(null);
  const [latestTrade, setLatestTrade] = useState<any | null>(null);

  useEffect(() => {
    // Only connect on client side
    if (typeof window === 'undefined') return;

    wsRef.current = new TradingWebSocket(topics);

    wsRef.current
      .onConnect(() => {
        setIsConnected(true);
      })
      .onDisconnect(() => {
        setIsConnected(false);
      })
      .onPortfolio((data) => {
        setPortfolio(data);
      })
      .onStatus((data) => {
        setStatus(data);
      })
      .onEquity((data) => {
        setLatestEquity(data);
      })
      .onDecisions((data) => {
        setLatestDecision(data);
      })
      .onTrades((data) => {
        setLatestTrade(data);
      })
      .onInitial((data) => {
        if (data.portfolio) setPortfolio(data.portfolio);
        if (data.status) setStatus(data.status);
      });

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [topics.join(',')]);

  const subscribe = useCallback((newTopics: string[]) => {
    wsRef.current?.subscribe(newTopics);
  }, []);

  const unsubscribe = useCallback((topicsToRemove: string[]) => {
    wsRef.current?.unsubscribe(topicsToRemove);
  }, []);

  return {
    isConnected,
    portfolio,
    status,
    latestEquity,
    latestDecision,
    latestTrade,
    subscribe,
    unsubscribe,
  };
}

// Combined hook using both SWR and WebSocket
export function useRealtimePortfolio() {
  const { data: swrData, error, mutate } = usePortfolio();
  const { portfolio: wsPortfolio, isConnected } = useWebSocket(['portfolio']);

  // Merge WebSocket updates with SWR data
  const data = wsPortfolio && isConnected
    ? { ...swrData, ...wsPortfolio }
    : swrData;

  return { data, error, mutate, isRealtime: isConnected };
}

export function useRealtimeEquityHistory() {
  const { data: swrData, error, mutate } = useEquityHistory();
  const { latestEquity, isConnected } = useWebSocket(['equity']);
  const [additionalPoints, setAdditionalPoints] = useState<EquityHistory[]>([]);

  // Add new equity points from WebSocket
  useEffect(() => {
    if (latestEquity && isConnected) {
      setAdditionalPoints((prev) => {
        // Keep only last 100 additional points
        const updated = [...prev, latestEquity].slice(-100);
        return updated;
      });
    }
  }, [latestEquity, isConnected]);

  // Combine SWR data with WebSocket updates
  const data = swrData
    ? [...swrData, ...additionalPoints.filter((p) =>
        !swrData.some((s) => s.timestamp === p.timestamp)
      )]
    : additionalPoints;

  return { data, error, mutate, isRealtime: isConnected };
}
