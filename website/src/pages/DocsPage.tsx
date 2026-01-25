import { useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function DocsPage() {
  useEffect(() => {
    const handleScroll = () => {
      const sections = document.querySelectorAll('section[id]')
      const sidebarLinks = document.querySelectorAll('.sidebar-section a')
      let current = ''

      sections.forEach(section => {
        const sectionTop = (section as HTMLElement).offsetTop
        if (window.scrollY >= sectionTop - 150) {
          current = section.getAttribute('id') || ''
        }
      })

      sidebarLinks.forEach(link => {
        link.classList.remove('active')
        if (link.getAttribute('href') === '#' + current) {
          link.classList.add('active')
        }
      })
    }

    window.addEventListener('scroll', handleScroll)
    handleScroll()
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <>
      <div className="cosmic-bg"></div>
      <div className="grid-overlay"></div>

      <nav>
        <Link to="/" className="logo">dr-manhattan</Link>
        <div className="nav-links">
          <Link to="/">Home</Link>
          <a href="#getting-started">Getting Started</a>
          <a href="#api">API Reference</a>
          <a href="#exchanges">Exchanges</a>
          <a href="https://github.com/guzus/dr-manhattan" className="github-btn" target="_blank" rel="noreferrer">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
            GitHub
          </a>
        </div>
      </nav>

      <div className="docs-layout">
        <aside className="sidebar">
          <div className="sidebar-section">
            <h3>Getting Started</h3>
            <a href="#getting-started">Introduction</a>
            <a href="#installation">Installation</a>
            <a href="#quick-start">Quick Start</a>
          </div>
          <div className="sidebar-section">
            <h3>API Reference</h3>
            <a href="#api">Overview</a>
            <a href="#markets">Markets</a>
            <a href="#orders">Orders</a>
            <a href="#positions">Positions</a>
            <a href="#websockets">WebSockets</a>
          </div>
          <div className="sidebar-section">
            <h3>Exchanges</h3>
            <a href="#exchanges">Overview</a>
            <a href="#polymarket">Polymarket</a>
            <a href="#kalshi">Kalshi</a>
            <a href="#opinion">Opinion</a>
            <a href="#limitless">Limitless</a>
            <a href="#predictfun">Predict.fun</a>
          </div>
          <div className="sidebar-section">
            <h3>Strategies</h3>
            <a href="#strategy-framework">Strategy Framework</a>
            <a href="#spread-strategy">Spread Strategy</a>
            <a href="#spike-strategy">Spike Strategy</a>
          </div>
          <div className="sidebar-section">
            <h3>Advanced</h3>
            <a href="#architecture">Architecture</a>
            <a href="#error-handling">Error Handling</a>
            <a href="#mcp-server">MCP Server</a>
          </div>
        </aside>

        <main className="docs-content">
          <section id="getting-started">
            <h1>Documentation</h1>
            <p>dr-manhattan is a CCXT-style unified API for prediction markets. It provides a simple, scalable, and extensible interface to interact with multiple prediction market platforms.</p>

            <div className="card-grid">
              <div className="card">
                <div className="card-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                </div>
                <h4>Unified Interface</h4>
                <p>One API for all prediction markets. Write once, deploy anywhere.</p>
              </div>
              <div className="card">
                <div className="card-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                </div>
                <h4>Real-time Data</h4>
                <p>WebSocket support for live orderbook and trade updates.</p>
              </div>
              <div className="card">
                <div className="card-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <h4>Type Safe</h4>
                <p>Full type hints throughout for better IDE support.</p>
              </div>
            </div>
          </section>

          <section id="installation">
            <h2>Installation</h2>
            <p>Install dr-manhattan using <code>uv</code> (recommended):</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">terminal</span>
              </div>
              <pre>{`# Create virtual environment and install
uv venv
uv pip install -e .

# Or install directly from GitHub
uv pip install -e git+https://github.com/guzus/dr-manhattan`}</pre>
            </div>

            <div className="callout callout-info">
              <p><strong>Note:</strong> dr-manhattan requires Python 3.11 or higher.</p>
            </div>
          </section>

          <section id="quick-start">
            <h2>Quick Start</h2>
            <p>Here's a simple example to get you started:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">example.py</span>
              </div>
              <pre>{`import dr_manhattan

# Initialize any exchange
polymarket = dr_manhattan.Polymarket({'timeout': 30})
opinion = dr_manhattan.Opinion({'timeout': 30})
limitless = dr_manhattan.Limitless({'timeout': 30})
predictfun = dr_manhattan.PredictFun({'timeout': 30})

# Fetch markets
markets = polymarket.fetch_markets()

for market in markets:
    print(f"{market.question}: {market.prices}")`}</pre>
            </div>
          </section>

          <section id="api">
            <h2>API Reference</h2>
            <p>All exchanges implement the same base interface, making it easy to switch between platforms or build cross-exchange applications.</p>

            <h3>Exchange Factory</h3>
            <p>Use the exchange factory to dynamically create exchange instances:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">factory.py</span>
              </div>
              <pre>{`from dr_manhattan import create_exchange, list_exchanges

# List available exchanges
print(list_exchanges())
# ['polymarket', 'kalshi', 'limitless', 'opinion', 'predictfun']

# Create exchange by name
exchange = create_exchange('polymarket', {'timeout': 30})`}</pre>
            </div>
          </section>

          <section id="markets">
            <h3>Markets</h3>
            <p>Fetch and query prediction markets:</p>

            <table>
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>fetch_markets()</code></td>
                  <td>Fetch all available markets</td>
                </tr>
                <tr>
                  <td><code>fetch_market(market_id)</code></td>
                  <td>Fetch a specific market by ID</td>
                </tr>
                <tr>
                  <td><code>fetch_orderbook(market_id)</code></td>
                  <td>Get the orderbook for a market</td>
                </tr>
              </tbody>
            </table>

            <h4>Market Model</h4>
            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">models/market.py</span>
              </div>
              <pre>{`class Market:
    id: str              # Unique market identifier
    question: str        # Market question
    outcomes: list       # Available outcomes (e.g., ["Yes", "No"])
    prices: dict         # Current prices for each outcome
    volume: float        # Total trading volume
    close_time: datetime # When the market closes
    status: str          # Market status (open, closed, resolved)`}</pre>
            </div>
          </section>

          <section id="orders">
            <h3>Orders</h3>
            <p>Create and manage orders:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">trading.py</span>
              </div>
              <pre>{`import dr_manhattan

# Initialize with authentication
polymarket = dr_manhattan.Polymarket({
    'private_key': 'your_private_key',
    'funder': 'your_funder_address',
})

# Create a buy order
order = polymarket.create_order(
    market_id="market_123",
    outcome="Yes",
    side=dr_manhattan.OrderSide.BUY,
    price=0.65,
    size=100,
    params={'token_id': 'token_id'}
)

# Cancel an order
polymarket.cancel_order(order.id)`}</pre>
            </div>
          </section>

          <section id="positions">
            <h3>Positions</h3>
            <p>Track your positions and balances:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">positions.py</span>
              </div>
              <pre>{`# Fetch balance
balance = polymarket.fetch_balance()
print(f"USDC: {balance['USDC']}")

# Fetch positions
positions = polymarket.fetch_positions()
for pos in positions:
    print(f"{pos.market_id}: {pos.size} @ {pos.avg_price}")`}</pre>
            </div>
          </section>

          <section id="websockets">
            <h3>WebSockets</h3>
            <p>Subscribe to real-time market data:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">websocket.py</span>
              </div>
              <pre>{`import asyncio
from dr_manhattan import PolymarketWS

async def main():
    ws = PolymarketWS()

    async def on_orderbook(data):
        print(f"Orderbook update: {data}")

    await ws.subscribe_orderbook("market_id", on_orderbook)
    await ws.run()

asyncio.run(main())`}</pre>
            </div>
          </section>

          <section id="exchanges">
            <h2>Supported Exchanges</h2>
            <p>dr-manhattan supports the following prediction market exchanges:</p>

            <div className="exchange-grid">
              <a href="#polymarket" className="exchange-card">
                <img src="/assets/polymarket.png" alt="Polymarket" />
                <span>Polymarket</span>
              </a>
              <a href="#kalshi" className="exchange-card">
                <img src="/assets/kalshi.jpeg" alt="Kalshi" />
                <span>Kalshi</span>
              </a>
              <a href="#opinion" className="exchange-card">
                <img src="/assets/opinion.jpg" alt="Opinion" />
                <span>Opinion</span>
              </a>
              <a href="#limitless" className="exchange-card">
                <img src="/assets/limitless.jpg" alt="Limitless" />
                <span>Limitless</span>
              </a>
              <a href="#predictfun" className="exchange-card">
                <img src="/assets/predict_fun.jpg" alt="Predict.fun" />
                <span>Predict.fun</span>
              </a>
            </div>
          </section>

          <section id="polymarket">
            <h3>Polymarket</h3>
            <p>Polymarket is the leading prediction market on Polygon. It uses USDC for trading and requires a wallet for authentication.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">polymarket_example.py</span>
              </div>
              <pre>{`import dr_manhattan

polymarket = dr_manhattan.Polymarket({
    'private_key': 'your_private_key',
    'funder': 'your_funder_address',
})

# Fetch active markets
markets = polymarket.fetch_markets()`}</pre>
            </div>
          </section>

          <section id="kalshi">
            <h3>Kalshi</h3>
            <p>Kalshi is a US-regulated prediction market exchange. It uses RSA-PSS authentication.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">kalshi_example.py</span>
              </div>
              <pre>{`import dr_manhattan

kalshi = dr_manhattan.Kalshi({
    'api_key': 'your_api_key',
    'private_key_path': '/path/to/private_key.pem',
})`}</pre>
            </div>
          </section>

          <section id="opinion">
            <h3>Opinion</h3>
            <p>Opinion is a prediction market on BNB Chain.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">opinion_example.py</span>
              </div>
              <pre>{`import dr_manhattan

opinion = dr_manhattan.Opinion({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
    'multi_sig_addr': 'your_multi_sig_addr'
})`}</pre>
            </div>
          </section>

          <section id="limitless">
            <h3>Limitless</h3>
            <p>Limitless is a prediction market platform with WebSocket support.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">limitless_example.py</span>
              </div>
              <pre>{`import dr_manhattan

limitless = dr_manhattan.Limitless({
    'private_key': 'your_private_key',
    'timeout': 30
})`}</pre>
            </div>
          </section>

          <section id="predictfun">
            <h3>Predict.fun</h3>
            <p>Predict.fun is a prediction market on BNB Chain with smart wallet support.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">predictfun_example.py</span>
              </div>
              <pre>{`import dr_manhattan

predictfun = dr_manhattan.PredictFun({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
    'use_smart_wallet': True,
    'smart_wallet_owner_private_key': 'your_owner_private_key',
    'smart_wallet_address': 'your_smart_wallet_address'
})`}</pre>
            </div>
          </section>

          <section id="strategy-framework">
            <h2>Strategy Framework</h2>
            <p>dr-manhattan provides a base class for building trading strategies with order tracking, position management, and event logging.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">my_strategy.py</span>
              </div>
              <pre>{`from dr_manhattan import Strategy

class MyStrategy(Strategy):
    def on_tick(self):
        self.log_status()
        self.place_bbo_orders()

# Run the strategy
strategy = MyStrategy(exchange, market_id="123")
strategy.run()`}</pre>
            </div>
          </section>

          <section id="spread-strategy">
            <h3>Spread Strategy</h3>
            <p>The spread strategy implements BBO (Best Bid/Offer) market making. It places orders at the best bid and ask prices with a configurable spread.</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">terminal</span>
              </div>
              <pre>{`uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spread_strategy.py --exchange opinion --market-id 813`}</pre>
            </div>
          </section>

          <section id="spike-strategy">
            <h3>Spike Strategy</h3>
            <p>The spike strategy implements mean reversion trading. It detects price spikes and places counter-trend orders.</p>
          </section>

          <section id="architecture">
            <h2>Architecture</h2>
            <p>dr-manhattan follows a clean, modular architecture:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">structure</span>
              </div>
              <pre>{`dr_manhattan/
├── base/               # Core abstractions
│   ├── exchange.py     # Abstract base class for exchanges
│   ├── exchange_client.py  # High-level trading client
│   ├── exchange_factory.py # Exchange instantiation
│   ├── strategy.py     # Strategy base class
│   ├── order_tracker.py    # Order event tracking
│   ├── websocket.py    # WebSocket base class
│   └── errors.py       # Exception hierarchy
├── exchanges/          # Exchange implementations
│   ├── polymarket.py
│   ├── polymarket_ws.py
│   ├── kalshi.py
│   ├── opinion.py
│   ├── limitless.py
│   ├── limitless_ws.py
│   ├── predictfun.py
│   └── predictfun_ws.py
├── models/             # Data models
│   ├── market.py
│   ├── order.py
│   ├── orderbook.py
│   └── position.py
├── strategies/         # Strategy implementations
└── utils/              # Utilities`}</pre>
            </div>

            <h3>Design Principles</h3>
            <ul>
              <li><strong>Unified Interface:</strong> All exchanges implement the same <code>Exchange</code> base class</li>
              <li><strong>Scalability:</strong> Adding new exchanges is straightforward - just implement the abstract methods</li>
              <li><strong>Simplicity:</strong> Clean abstractions with minimal dependencies</li>
              <li><strong>Type Safety:</strong> Full type hints throughout the codebase</li>
            </ul>
          </section>

          <section id="error-handling">
            <h3>Error Handling</h3>
            <p>All errors inherit from <code>DrManhattanError</code>:</p>

            <table>
              <thead>
                <tr>
                  <th>Error</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>ExchangeError</code></td>
                  <td>Exchange-specific errors</td>
                </tr>
                <tr>
                  <td><code>NetworkError</code></td>
                  <td>Connectivity issues</td>
                </tr>
                <tr>
                  <td><code>RateLimitError</code></td>
                  <td>Rate limit exceeded</td>
                </tr>
                <tr>
                  <td><code>AuthenticationError</code></td>
                  <td>Auth failures</td>
                </tr>
                <tr>
                  <td><code>InsufficientFunds</code></td>
                  <td>Not enough balance</td>
                </tr>
                <tr>
                  <td><code>InvalidOrder</code></td>
                  <td>Invalid order parameters</td>
                </tr>
                <tr>
                  <td><code>MarketNotFound</code></td>
                  <td>Market doesn't exist</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section id="mcp-server">
            <h3>MCP Server</h3>
            <p>Trade prediction markets directly from Claude using the Model Context Protocol (MCP). Choose between the hosted remote server (recommended) or run locally.</p>

            <h4>Remote Server (Recommended)</h4>
            <p>Connect to the hosted MCP server without any local installation:</p>

            <ol>
              <li><strong>Connect Your Wallet:</strong> Go to <Link to="/approve">the approval page</Link> to connect your Polymarket wallet and sign an authentication message.</li>
              <li><strong>Copy Configuration:</strong> After signing, copy the generated configuration.</li>
              <li><strong>Add to Claude:</strong> Paste into <code>~/.claude/settings.json</code> (Claude Code) or <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> (Claude Desktop on macOS).</li>
            </ol>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">settings.json</span>
              </div>
              <pre>{`{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "0xYourWalletAddress",
        "X-Polymarket-Auth-Signature": "0xYourSignature...",
        "X-Polymarket-Auth-Timestamp": "1706123456"
      }
    }
  }
}`}</pre>
            </div>

            <div className="callout callout-info">
              <p><strong>Security:</strong> Your private key never leaves your wallet. The server uses operator mode where you approve it to trade on your behalf. Signatures expire after 24 hours.</p>
            </div>

            <h4>Local Server</h4>
            <p>Run the MCP server locally for full control:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">terminal</span>
              </div>
              <pre>{`# Install with MCP dependencies
uv sync --extra mcp

# Configure credentials
cp .env.example .env
# Edit .env with your POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER`}</pre>
            </div>

            <p>Add to your Claude Code settings:</p>

            <div className="code-block">
              <div className="code-header">
                <div className="dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
                <span className="filename">settings.json</span>
              </div>
              <pre>{`{
  "mcpServers": {
    "dr-manhattan": {
      "command": "/path/to/dr-manhattan/.venv/bin/python",
      "args": ["-m", "dr_manhattan.mcp.server"],
      "cwd": "/path/to/dr-manhattan"
    }
  }
}`}</pre>
            </div>

            <h4>Available Commands</h4>
            <p>After restarting Claude, you can:</p>
            <ul>
              <li>"Show my Polymarket balance"</li>
              <li>"Find active prediction markets"</li>
              <li>"Buy 10 USDC of Yes on market X at 0.55"</li>
              <li>"Cancel all my open orders"</li>
            </ul>
          </section>
        </main>
      </div>

      <footer className="docs-footer">
        <div className="footer-links">
          <a href="https://github.com/guzus/dr-manhattan" target="_blank" rel="noreferrer">GitHub</a>
          <a href="https://x.com/drmanhattan_oss" target="_blank" rel="noreferrer">Twitter</a>
          <a href="https://t.me/dr_manhattan_oss" target="_blank" rel="noreferrer">Telegram</a>
          <a href="https://github.com/guzus/dr-manhattan/issues" target="_blank" rel="noreferrer">Issues</a>
        </div>
        <p className="footer-copy">MIT License. Built for the prediction market community.</p>
      </footer>
    </>
  )
}
