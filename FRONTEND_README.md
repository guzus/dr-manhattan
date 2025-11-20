# Dr Manhattan Debug Dashboard

A TypeScript + Next.js + shadcn/ui + Tailwind CSS frontend for debugging prediction market trading strategies.

## Features

- Real-time monitoring of positions, balances, orders, and markets
- Aggregated view across all exchanges
- Per-exchange detailed views
- Auto-refresh every 5 seconds
- Clean, modern UI with shadcn/ui components

## Architecture

### Backend (FastAPI)
- **Location**: `/api/server.py`
- **Port**: 8000
- **Endpoints**:
  - `GET /api/health` - Health check
  - `GET /api/exchanges` - List configured exchanges
  - `GET /api/balances` - Get balances for all exchanges
  - `GET /api/positions` - Get positions for all exchanges
  - `GET /api/orders` - Get open orders for all exchanges
  - `GET /api/markets` - Get markets (optional: exchange_id, limit)

### Frontend (Next.js)
- **Location**: `/frontend`
- **Port**: 3000
- **Tech Stack**:
  - Next.js 16 with App Router
  - TypeScript
  - Tailwind CSS
  - shadcn/ui components

## Getting Started

### 1. Start Backend Server

```bash
uv run python api/server.py
```

The API will be available at `http://localhost:8000`

### 2. Start Frontend

```bash
cd frontend
npm run dev
```

The dashboard will be available at `http://localhost:3000`

### 3. Configure Exchanges (Optional)

To see live data, configure your exchange credentials in `.env`:

```bash
cp .env.example .env
# Edit .env with your credentials
```

Without credentials, the dashboard will show the UI structure with no data.

## Dashboard Views

### Overview Tab
- Aggregated balances across all exchanges
- All positions with PnL calculations
- All open orders
- Summary statistics

### Positions Tab
- Detailed position table
- Market ID, outcome, size, prices
- Cost basis and current value
- Unrealized PnL and PnL percentage

### Orders Tab
- Active orders across all exchanges
- Order details: price, size, filled amount
- Status tracking (open, filled, partially filled, etc.)
- Side indicators (buy/sell)

### Markets Tab
- Available markets (first 20)
- Market questions and outcomes
- Volume and liquidity
- Current prices
- Bid-ask spread

### Exchange-Specific Tabs
- Per-exchange detailed views
- Filtered balances, positions, orders, markets
- Same detailed information as overview tabs

## Development

### API Client
Location: `/frontend/lib/api.ts`

Custom hook for data fetching: `/frontend/hooks/use-api-data.ts`

### Components
- `BalancesCard` - Display balances with total
- `PositionsTable` - Positions with PnL
- `OrdersTable` - Active orders
- `MarketsTable` - Available markets

### Types
TypeScript types: `/frontend/lib/types.ts`

## Customization

### Refresh Interval
Edit `app/page.tsx`:
```typescript
const [refreshInterval, setRefreshInterval] = useState(5000) // 5 seconds
```

### API Base URL
Set environment variable:
```bash
NEXT_PUBLIC_API_URL=http://your-api-url:8000
```

### Markets Limit
Edit the API call in `app/page.tsx`:
```typescript
api.getMarkets(undefined, 20) // Change 20 to desired limit
```

## Troubleshooting

### Backend not starting
- Check if port 8000 is available
- Ensure all Python dependencies are installed: `uv sync`
- Check API logs for errors

### Frontend not connecting to backend
- Verify backend is running on port 8000
- Check CORS settings in `api/server.py`
- Verify `NEXT_PUBLIC_API_URL` environment variable

### No data showing
- Check if exchanges are configured in `.env`
- Verify API credentials are correct
- Check browser console for API errors

## Production Deployment

### Backend
```bash
# Use a production ASGI server
uv add gunicorn
gunicorn api.server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Frontend
```bash
cd frontend
npm run build
npm start
```

Or deploy to Vercel:
```bash
cd frontend
vercel deploy
```
