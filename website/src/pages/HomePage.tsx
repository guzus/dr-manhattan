import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

export default function HomePage() {
  const [showIntro, setShowIntro] = useState(true)

  useEffect(() => {
    const timer = setTimeout(() => {
      setShowIntro(false)
    }, 2000)
    return () => clearTimeout(timer)
  }, [])

  const copyInstall = () => {
    navigator.clipboard.writeText('uv pip install -e git+https://github.com/guzus/dr-manhattan')
  }

  return (
    <>
      {showIntro && (
        <div className={`marvel-intro ${!showIntro ? 'fade-out' : ''}`}>
          <div className="flip-book">
            <div className="flip-page"><img src="/assets/polymarket.png" alt="Polymarket" /></div>
            <div className="flip-page"><img src="/assets/kalshi.jpeg" alt="Kalshi" /></div>
            <div className="flip-page"><img src="/assets/opinion.jpg" alt="Opinion" /></div>
            <div className="flip-page"><img src="/assets/limitless.jpg" alt="Limitless" /></div>
            <div className="flip-page"><img src="/assets/predict_fun.jpg" alt="Predict.fun" /></div>
          </div>
          <div className="color-overlay"></div>
          <div className="logo-reveal">
            <div className="logo-text">dr-manhattan</div>
          </div>
        </div>
      )}

      <nav>
        <Link to="/" className="logo">dr-manhattan</Link>
        <div className="nav-links">
          <Link to="/docs">Docs</Link>
          <a href="https://github.com/guzus/dr-manhattan" className="nav-icon" target="_blank" rel="noreferrer" title="GitHub">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
          </a>
        </div>
      </nav>

      <section className="hero">
        <div className="hero-content">
          <div className="hero-badge">Open Source</div>
          <h1><span className="glow">dr-manhattan</span></h1>
          <p className="hero-tagline">CCXT for prediction markets. Simple, scalable, and easy to extend.</p>
          <div className="hero-actions">
            <Link to="/approve" className="btn-primary">Integrate MCP Server</Link>
            <a href="https://github.com/guzus/dr-manhattan" className="btn-secondary" target="_blank" rel="noreferrer">
              <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
              View on GitHub
            </a>
          </div>

          <div className="exchanges-preview">
            <span>Supported Exchanges</span>
            <div className="exchange-logos">
              <img src="/assets/polymarket.png" alt="Polymarket" className="exchange-logo" />
              <img src="/assets/kalshi.jpeg" alt="Kalshi" className="exchange-logo" />
              <img src="/assets/opinion.jpg" alt="Opinion" className="exchange-logo" />
              <img src="/assets/limitless.jpg" alt="Limitless" className="exchange-logo" />
              <img src="/assets/predict_fun.jpg" alt="Predict.fun" className="exchange-logo" />
            </div>
          </div>
        </div>
      </section>

      <section className="code-section" id="code">
        <div className="section-header">
          <h2>Simple, Unified Interface</h2>
          <p>Write exchange-agnostic code that works across all prediction markets</p>
        </div>

        <div className="code-container">
          <div className="code-header">
            <span className="code-dot"></span>
            <span className="code-dot"></span>
            <span className="code-dot"></span>
            <span className="code-filename">example.py</span>
          </div>
          <div className="code-block">
            <pre>
<span className="kw">import</span> dr_manhattan{'\n'}
{'\n'}
<span className="cm"># Initialize any exchange with the same interface</span>{'\n'}
polymarket = dr_manhattan.<span className="fn">Polymarket</span>({'{'}<span className="st">'timeout'</span>: <span className="nu">30</span>{'}'}){'\n'}
opinion = dr_manhattan.<span className="fn">Opinion</span>({'{'}<span className="st">'timeout'</span>: <span className="nu">30</span>{'}'}){'\n'}
limitless = dr_manhattan.<span className="fn">Limitless</span>({'{'}<span className="st">'timeout'</span>: <span className="nu">30</span>{'}'}){'\n'}
{'\n'}
<span className="cm"># Fetch markets from any platform</span>{'\n'}
markets = polymarket.<span className="fn">fetch_markets</span>(){'\n'}
{'\n'}
<span className="kw">for</span> market <span className="kw">in</span> markets:{'\n'}
    <span className="fn">print</span>(<span className="st">f"</span>{'{'}market.question{'}'}: {'{'}market.prices{'}'}<span className="st">"</span>)</pre>
          </div>
        </div>
      </section>

      <section className="features-section" id="features">
        <div className="section-header">
          <h2>Built for Developers</h2>
          <p>Everything you need to build prediction market applications</p>
        </div>

        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            </div>
            <h3>Unified Interface</h3>
            <p>One API to rule them all. Write code once and deploy across Polymarket, Kalshi, Opinion, and Limitless.</p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </div>
            <h3>WebSocket Support</h3>
            <p>Real-time market data streaming with built-in WebSocket connections for live orderbook and trade updates.</p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
            </div>
            <h3>Strategy Framework</h3>
            <p>Base class for building trading strategies with order tracking, position management, and event logging.</p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            </div>
            <h3>Easily Extensible</h3>
            <p>Add new exchanges by implementing abstract methods. Clean architecture makes integration straightforward.</p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <h3>Type Safe</h3>
            <p>Full type hints throughout the codebase. Catch errors early and enjoy superior IDE autocomplete.</p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            </div>
            <h3>Order Management</h3>
            <p>Create, cancel, and track orders with standardized error handling across all supported exchanges.</p>
          </div>
        </div>
      </section>

      <section className="install-section" id="install">
        <div className="section-header">
          <h2>Get Started in Seconds</h2>
          <p>Install with uv and start building</p>
        </div>

        <div className="install-box">
          <code>uv pip install -e git+https://github.com/guzus/dr-manhattan</code>
          <button className="copy-btn" onClick={copyInstall}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          </button>
        </div>
      </section>

      <footer>
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
