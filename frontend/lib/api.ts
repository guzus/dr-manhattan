import {
  ExchangeInfo,
  BalanceResponse,
  PositionResponse,
  OrderResponse,
  MarketResponse
} from './types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`)

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`)
  }

  return response.json()
}

export const api = {
  getExchanges: () => fetchAPI<ExchangeInfo[]>('/api/exchanges'),
  getBalances: () => fetchAPI<BalanceResponse[]>('/api/balances'),
  getPositions: () => fetchAPI<PositionResponse[]>('/api/positions'),
  getOrders: () => fetchAPI<OrderResponse[]>('/api/orders'),
  getMarkets: (exchangeId?: string, limit?: number) => {
    const params = new URLSearchParams()
    if (exchangeId) params.append('exchange_id', exchangeId)
    if (limit) params.append('limit', limit.toString())

    const query = params.toString()
    return fetchAPI<MarketResponse[]>(`/api/markets${query ? `?${query}` : ''}`)
  },
  healthCheck: () => fetchAPI<{ status: string; exchanges: string[]; timestamp: string }>('/api/health')
}
