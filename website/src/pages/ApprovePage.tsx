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
  const [expiry, setExpiry] = useState<number>(EXPIRY_OPTIONS[0].value)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [showRevoke, setShowRevoke] = useState(false)

  // Check if already approved
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
      setStep(2)
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
      setStep(3)
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
    <div className="onboarding-container">
      <div className="onboarding-header">
        <Link to="/" className="back-link">Back to Home</Link>
        <h1>Connect to <span className="glow">Dr. Manhattan</span></h1>
        <p>Set up your wallet to trade on Polymarket via AI agents</p>
      </div>

      <div className="steps-container">
        {/* Step indicator */}
        <div className="steps-indicator">
          <div className={`step-dot ${step >= 1 ? 'active' : ''}`}>1</div>
          <div className="step-line" />
          <div className={`step-dot ${step >= 2 ? 'active' : ''}`}>2</div>
          <div className="step-line" />
          <div className={`step-dot ${step >= 3 ? 'active' : ''}`}>3</div>
        </div>

        {/* Step 1: Connect Wallet */}
        <div className={`step-card ${step === 1 ? 'current' : step > 1 ? 'completed' : ''}`}>
          <h2>Step 1: Connect Wallet</h2>
          <p>Connect your Polymarket wallet to get started.</p>

          <div className="connect-button-wrapper">
            <ConnectButton />
          </div>

          {isConnected && (
            <div className="step-actions">
              {isApproved ? (
                <div className="approval-status success">
                  Operator already approved
                  <button className="btn-primary" onClick={() => setStep(2)}>
                    Continue
                  </button>
                </div>
              ) : (
                <>
                  <p className="info-text">
                    Approve Dr. Manhattan as an operator to trade on your behalf.
                    This is a one-time on-chain transaction.
                  </p>
                  <button
                    className="btn-primary"
                    onClick={handleApproveOperator}
                    disabled={isWritePending}
                  >
                    {isWritePending ? 'Approving...' : 'Approve Operator'}
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {/* Step 2: Sign Authentication */}
        <div className={`step-card ${step === 2 ? 'current' : step > 2 ? 'completed' : 'disabled'}`}>
          <h2>Step 2: Sign Authentication</h2>
          <p>Sign a message to prove you own this wallet. This is free (no gas).</p>

          {step >= 2 && (
            <div className="step-actions">
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
                <p className="expiry-hint">
                  Longer expiry = less frequent re-authentication, but higher risk if leaked.
                </p>
              </div>
              <button
                className="btn-primary"
                onClick={handleSignAuth}
              >
                Sign Message
              </button>
            </div>
          )}
        </div>

        {/* Step 3: Get Config */}
        <div className={`step-card ${step === 3 ? 'current' : 'disabled'}`}>
          <h2>Step 3: Copy Configuration</h2>
          <p>Add this to your Claude settings to start trading.</p>

          {step === 3 && (
            <div className="config-section">
              <div className="config-meta">
                <span className="expiry-badge">Expires in {getExpiryLabel(expiry)}</span>
              </div>
              <div className="config-header">
                <span>~/.claude/settings.json</span>
                <button className="copy-btn" onClick={copyConfig}>
                  {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <pre className="config-code">{configSnippet}</pre>

              <div className="success-message">
                You're all set! Paste this config and restart Claude.
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {/* Revoke Section */}
        {isConnected && isApproved && (
          <div className="revoke-section">
            <button
              className="btn-text"
              onClick={() => setShowRevoke(!showRevoke)}
            >
              {showRevoke ? 'Cancel' : 'Revoke Access'}
            </button>

            {showRevoke && (
              <div className="revoke-card">
                <h3>Revoke Operator Access</h3>
                <p>This will immediately revoke Dr. Manhattan's ability to trade on your behalf. Any existing signatures will become invalid.</p>
                <button
                  className="btn-danger"
                  onClick={handleRevokeOperator}
                  disabled={isWritePending}
                >
                  {isWritePending ? 'Revoking...' : 'Revoke Access'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
