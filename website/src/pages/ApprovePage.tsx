import { useState } from 'react'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { useAccount, useSignMessage, useWriteContract, useReadContract } from 'wagmi'
import { Link } from 'react-router-dom'

import { createAuthMessage, OPERATOR_ADDRESS, CTF_CONTRACT_ADDRESS, CTF_ABI, EXPIRY_OPTIONS } from '../wagmi'

export default function ApprovePage() {
  const { address, isConnected } = useAccount()
  const { signMessageAsync } = useSignMessage()
  const { writeContractAsync, isPending: isWritePending } = useWriteContract()

  const [step, setStep] = useState(1)
  const [signature, setSignature] = useState<string | null>(null)
  const [timestamp, setTimestamp] = useState<number | null>(null)
  const [expiry, setExpiry] = useState<number>(EXPIRY_OPTIONS[1].value)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [showRevoke, setShowRevoke] = useState(false)

  const { data: isApproved, refetch: refetchApproval } = useReadContract({
    address: CTF_CONTRACT_ADDRESS,
    abi: CTF_ABI,
    functionName: 'isApprovedForAll',
    args: address ? [address, OPERATOR_ADDRESS] : undefined,
  })

  const handleApproveOperator = async () => {
    if (!address) return
    setError(null)

    try {
      await writeContractAsync({
        address: CTF_CONTRACT_ADDRESS,
        abi: CTF_ABI,
        functionName: 'setApprovalForAll',
        args: [OPERATOR_ADDRESS, true],
      })
      await refetchApproval()
      setStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve operator')
    }
  }

  const handleRevokeOperator = async () => {
    if (!address) return
    setError(null)

    try {
      await writeContractAsync({
        address: CTF_CONTRACT_ADDRESS,
        abi: CTF_ABI,
        functionName: 'setApprovalForAll',
        args: [OPERATOR_ADDRESS, false],
      })
      await refetchApproval()
      setShowRevoke(false)
      setStep(1)
      setSignature(null)
      setTimestamp(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke operator')
    }
  }

  const handleSignAuth = async () => {
    if (!address) return
    setError(null)

    try {
      const ts = Math.floor(Date.now() / 1000)
      const message = createAuthMessage(address, ts, expiry)
      const sig = await signMessageAsync({ message })
      setSignature(sig)
      setTimestamp(ts)
      setStep(4)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sign message')
    }
  }

  const getExpiryLabel = (seconds: number): string => {
    const option = EXPIRY_OPTIONS.find(o => o.value === seconds)
    return option?.label || `${seconds} seconds`
  }

  const configSnippet = signature && timestamp ? `{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "${address}",
        "X-Polymarket-Auth-Signature": "${signature}",
        "X-Polymarket-Auth-Timestamp": "${timestamp}",
        "X-Polymarket-Auth-Expiry": "${expiry}"
      }
    }
  }
}` : ''

  const copyConfig = () => {
    navigator.clipboard.writeText(configSnippet)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="guide-container">
      <nav className="guide-nav">
        <Link to="/" className="logo">dr-manhattan</Link>
        <div className="nav-links">
          <Link to="/docs">Docs</Link>
          <a href="https://github.com/guzus/dr-manhattan" className="nav-icon" target="_blank" rel="noreferrer" title="GitHub">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
          </a>
        </div>
      </nav>

      <div className="guide-content">
        <div className="guide-header">
          <h1>MCP Server Integration Guide</h1>
          <p className="guide-subtitle">Connect Claude to Polymarket through Dr. Manhattan's MCP server</p>
        </div>

        {/* Introduction */}
        <section className="guide-section">
          <h2>What is an MCP Server?</h2>
          <p>
            MCP (Model Context Protocol) is an open standard that allows AI assistants like Claude to securely
            interact with external services. Dr. Manhattan provides an MCP server that enables Claude to:
          </p>
          <ul className="guide-list">
            <li>Fetch real-time market data from Polymarket</li>
            <li>View your positions and balances</li>
            <li>Place and manage orders on your behalf</li>
            <li>Execute trading strategies you define</li>
          </ul>
        </section>

        {/* How it Works */}
        <section className="guide-section">
          <h2>How Does It Work?</h2>
          <p>
            Dr. Manhattan uses <strong>Operator Mode</strong>, a secure delegation mechanism built into Polymarket's
            smart contracts. Here's how it works:
          </p>
          <div className="info-card">
            <h3>Operator Mode Explained</h3>
            <ol className="guide-list numbered">
              <li>
                <strong>You approve Dr. Manhattan as an operator</strong> - This is an on-chain transaction that
                grants permission to trade on your behalf. You can revoke this at any time.
              </li>
              <li>
                <strong>You sign an authentication message</strong> - This proves you own the wallet and creates
                a time-limited session. No private keys are shared.
              </li>
              <li>
                <strong>Claude sends trading requests to the MCP server</strong> - The server validates your
                signature and executes trades through Polymarket's API.
              </li>
            </ol>
          </div>
          <p className="security-note">
            Your private keys never leave your wallet. The operator can only trade positions - it cannot
            withdraw funds or transfer assets.
          </p>
        </section>

        {/* Security */}
        <section className="guide-section">
          <h2>Security Considerations</h2>
          <div className="security-grid">
            <div className="security-item safe">
              <h4>What the operator CAN do:</h4>
              <ul>
                <li>Place buy/sell orders on Polymarket</li>
                <li>Cancel your open orders</li>
                <li>View your positions and balances</li>
              </ul>
            </div>
            <div className="security-item restricted">
              <h4>What the operator CANNOT do:</h4>
              <ul>
                <li>Withdraw funds from your wallet</li>
                <li>Transfer your assets to another address</li>
                <li>Access your private keys</li>
                <li>Trade after you revoke access</li>
              </ul>
            </div>
          </div>
          <p>
            The operator contract is Polymarket's official CTF Exchange contract at{' '}
            <a href={`https://polygonscan.com/address/${CTF_CONTRACT_ADDRESS}`} target="_blank" rel="noreferrer" className="code-link">
              {CTF_CONTRACT_ADDRESS.slice(0, 10)}...{CTF_CONTRACT_ADDRESS.slice(-8)}
            </a>
          </p>
        </section>

        {/* Setup Steps */}
        <section className="guide-section">
          <h2>Setup Steps</h2>

          {/* Step 1 */}
          <div className="setup-step">
            <div className="step-header">
              <span className={`step-number ${step >= 1 ? 'active' : ''}`}>1</span>
              <div>
                <h3>Connect Your Wallet</h3>
                <p>Connect the wallet you use for Polymarket trading.</p>
              </div>
            </div>
            <div className="step-content">
              <div className="connect-wrapper">
                <ConnectButton />
              </div>
              {isConnected && (
                <div className="step-status success">
                  Connected: {address?.slice(0, 6)}...{address?.slice(-4)}
                  {!isApproved && step === 1 && (
                    <button className="btn-small" onClick={() => setStep(2)}>Continue</button>
                  )}
                  {isApproved && step === 1 && (
                    <button className="btn-small" onClick={() => setStep(3)}>Continue</button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Step 2 */}
          <div className={`setup-step ${step < 2 ? 'locked' : ''}`}>
            <div className="step-header">
              <span className={`step-number ${step >= 2 ? 'active' : ''} ${isApproved ? 'completed' : ''}`}>2</span>
              <div>
                <h3>Approve Operator Access</h3>
                <p>Grant Dr. Manhattan permission to trade on your behalf.</p>
              </div>
            </div>
            {step >= 2 && (
              <div className="step-content">
                <div className="step-explanation">
                  <p>
                    This transaction calls <code>setApprovalForAll</code> on Polymarket's CTF Exchange contract,
                    allowing our operator address to execute trades for your account.
                  </p>
                  <div className="contract-details">
                    <div className="detail-row">
                      <span>Contract:</span>
                      <a href={`https://polygonscan.com/address/${CTF_CONTRACT_ADDRESS}`} target="_blank" rel="noreferrer">
                        CTF Exchange (Polygon)
                      </a>
                    </div>
                    <div className="detail-row">
                      <span>Operator:</span>
                      <a href={`https://polygonscan.com/address/${OPERATOR_ADDRESS}`} target="_blank" rel="noreferrer">
                        {OPERATOR_ADDRESS.slice(0, 10)}...{OPERATOR_ADDRESS.slice(-8)}
                      </a>
                    </div>
                    <div className="detail-row">
                      <span>Function:</span>
                      <code>setApprovalForAll(operator, true)</code>
                    </div>
                  </div>
                </div>
                {isApproved ? (
                  <div className="step-status success">
                    Operator approved
                    <button className="btn-small" onClick={() => setStep(3)}>Continue</button>
                  </div>
                ) : (
                  <button className="btn-primary" onClick={handleApproveOperator} disabled={isWritePending}>
                    {isWritePending ? 'Confirming...' : 'Approve Operator'}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Step 3 */}
          <div className={`setup-step ${step < 3 ? 'locked' : ''}`}>
            <div className="step-header">
              <span className={`step-number ${step >= 3 ? 'active' : ''}`}>3</span>
              <div>
                <h3>Sign Authentication Message</h3>
                <p>Create a time-limited session for the MCP server.</p>
              </div>
            </div>
            {step >= 3 && (
              <div className="step-content">
                <div className="step-explanation">
                  <p>
                    This signature proves you own the wallet without exposing your private key.
                    The MCP server validates this signature with each request.
                  </p>
                  <p>
                    Choose how long the signature should be valid. Shorter durations are more secure
                    but require more frequent re-authentication.
                  </p>
                </div>
                <div className="expiry-selector">
                  <label>Signature validity:</label>
                  <div className="expiry-options">
                    {EXPIRY_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        className={`expiry-option ${expiry === option.value ? 'selected' : ''}`}
                        onClick={() => setExpiry(option.value)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
                {signature ? (
                  <div className="step-status success">
                    Signature created (valid for {getExpiryLabel(expiry)})
                    <button className="btn-small" onClick={() => setStep(4)}>Continue</button>
                  </div>
                ) : (
                  <button className="btn-primary" onClick={handleSignAuth}>
                    Sign Message
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Step 4 */}
          <div className={`setup-step ${step < 4 ? 'locked' : ''}`}>
            <div className="step-header">
              <span className={`step-number ${step >= 4 ? 'active' : ''}`}>4</span>
              <div>
                <h3>Configure Claude</h3>
                <p>Add the MCP server configuration to Claude.</p>
              </div>
            </div>
            {step >= 4 && (
              <div className="step-content">
                <div className="step-explanation">
                  <p>
                    Copy this configuration to your Claude settings file. The headers contain your
                    wallet address and signature for authentication.
                  </p>
                  <p>
                    <strong>File location:</strong> <code>~/.claude/settings.json</code>
                  </p>
                </div>
                <div className="config-block">
                  <div className="config-header">
                    <span>~/.claude/settings.json</span>
                    <div className="config-actions">
                      <span className="expiry-badge">Expires in {getExpiryLabel(expiry)}</span>
                      <button className="copy-btn" onClick={copyConfig}>
                        {copied ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                  </div>
                  <pre className="config-code">{configSnippet}</pre>
                </div>
                <div className="final-steps">
                  <h4>Final Steps:</h4>
                  <ol>
                    <li>Open <code>~/.claude/settings.json</code> in a text editor</li>
                    <li>Paste the configuration above</li>
                    <li>Save the file and restart Claude</li>
                    <li>Ask Claude to check your Polymarket positions</li>
                  </ol>
                </div>
              </div>
            )}
          </div>
        </section>

        {error && (
          <div className="error-message">{error}</div>
        )}

        {/* Revoke Section */}
        {isConnected && isApproved && (
          <section className="guide-section revoke-section">
            <h2>Revoke Access</h2>
            <p>
              You can revoke operator access at any time. This immediately prevents any further
              trades from being executed on your behalf.
            </p>
            {showRevoke ? (
              <div className="revoke-confirm">
                <p>Are you sure? This will invalidate all existing sessions.</p>
                <div className="revoke-actions">
                  <button className="btn-danger" onClick={handleRevokeOperator} disabled={isWritePending}>
                    {isWritePending ? 'Revoking...' : 'Confirm Revoke'}
                  </button>
                  <button className="btn-secondary" onClick={() => setShowRevoke(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button className="btn-outline-danger" onClick={() => setShowRevoke(true)}>
                Revoke Operator Access
              </button>
            )}
          </section>
        )}

        {/* FAQ */}
        <section className="guide-section">
          <h2>Frequently Asked Questions</h2>
          <div className="faq-list">
            <div className="faq-item">
              <h4>Is this safe?</h4>
              <p>
                Yes. The operator can only trade positions on Polymarket - it cannot withdraw or
                transfer your funds. You maintain full control and can revoke access instantly.
              </p>
            </div>
            <div className="faq-item">
              <h4>What happens when my signature expires?</h4>
              <p>
                You'll need to sign a new authentication message. The operator approval remains
                active, so you only need to repeat Step 3.
              </p>
            </div>
            <div className="faq-item">
              <h4>Can I use this with multiple wallets?</h4>
              <p>
                Yes! Repeat this process for each wallet. You can configure multiple MCP servers
                in Claude's settings with different names.
              </p>
            </div>
            <div className="faq-item">
              <h4>Where can I see the source code?</h4>
              <p>
                Dr. Manhattan is fully open source. View the code on{' '}
                <a href="https://github.com/guzus/dr-manhattan" target="_blank" rel="noreferrer">GitHub</a>.
              </p>
            </div>
          </div>
        </section>
      </div>

      <footer className="guide-footer">
        <p>MIT License. Built for the prediction market community.</p>
      </footer>
    </div>
  )
}
