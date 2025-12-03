export interface ExchangeInfo {
  id: string
  name: string
  enabled: boolean
}

export interface BalanceResponse {
  exchange: string
  balances: Record<string, number>
}

export interface PositionResponse {
  exchange: string
  market_id: string
  outcome: string
  size: number
  average_price: number
  current_price: number
  cost_basis: number
  current_value: number
  unrealized_pnl: number
  unrealized_pnl_percent: number
}

export interface OrderResponse {
  exchange: string
  id: string
  market_id: string
  outcome: string
  side: string
  price: number
  size: number
  filled: number
  status: string
  created_at: string
  updated_at: string | null
}

export interface MarketResponse {
  exchange: string
  id: string
  question: string
  outcomes: string[]
  close_time: string | null
  volume: number
  liquidity: number
  prices: Record<string, number>
  is_binary: boolean
  is_open: boolean
  spread: number | null
}
