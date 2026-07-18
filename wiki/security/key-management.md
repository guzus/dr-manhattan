# Key management: keyless QA now, remote signing next

How dr-manhattan handles trading credentials across development, QA, and
production - and the path to sending orders without a raw private key ever
sitting in agent-reachable memory.

## Threat model

dr-manhattan executes real-money, on-chain, irreversible trades. The standing
setup (raw Ethereum private keys and venue API secrets in a local `.env`) has a
worst-case blast radius of direct theft with no recourse, and the project
deliberately points agents at itself ("Run and Debug yourself PROACTIVELY"),
runs an issue-to-PR agent loop, and exposes order placement over MCP. The two
failure classes to engineer away:

1. An agent (or any semi-trusted code: PR branch, generated strategy) runs a
   flow that submits live orders because real credentials were reachable.
2. Credentials exfiltrate - through a log, a prompt injection, a dependency, or
   a compromised sandbox.

Both are addressed structurally, never by prompt-level instructions.

## Credential tiers

| Tier | What runs | Where | Credentials present |
|---|---|---|---|
| 0 | lint, unit tests, build (`ci.yml`) | GitHub-hosted CI | none |
| 1 | public live reads (`contract-drift.yml`, `qa-live.yml` tier1) | CI runner / E2B sandbox | none |
| 2 | order lifecycle QA (`qa-live.yml` tier2) | E2B sandbox, egress-firewalled | Kalshi DEMO only (mock funds) |
| 3 | real-money strategies | operator-controlled host, human-supervised | production keys via signer (below) |

Rules that hold across tiers:

- QA is keyless by contract. `scripts/qa/run_live_qa.py` refuses to start if a
  production-shaped secret is present in its environment.
- Demo/testnet credentials use distinct variable names (`KALSHI_QA_DEMO_*`)
  from production (`KALSHI_*`) so the tripwire can tell them apart and a copied
  `.env` cannot silently promote a QA run to production.
- Tier 2 sandboxes get a deny-all egress firewall plus an explicit allowlist
  (`scripts/qa/spawn_qa_sandbox.py`), so even a fully compromised QA payload
  can only reach the demo venue and the package toolchain.
- Only Kalshi (`KALSHI_DEMO=true` -> demo-api.kalshi.co) and Predict.fun
  (`PREDICTFUN_TESTNET=true`) offer test environments today. Polymarket,
  Opinion, and Limitless have none, so they are never part of automated
  write-QA; their write paths are exercised only at tier 3.

## Storage layer: 1Password

1Password is the vault and injection mechanism for everything API-key-shaped:

- **Vault layout**: `dr-manhattan-qa` holds demo/testnet credentials (the only
  vault CI can read); `dr-manhattan-prod` holds production secrets and is never
  granted to any automation identity.
- **CI**: a [service account](https://developer.1password.com/docs/service-accounts/)
  scoped to `dr-manhattan-qa`, consumed by
  [`1password/load-secrets-action`](https://github.com/1Password/load-secrets-action)
  in `qa-live.yml` via `op://dr-manhattan-qa/kalshi-demo/...` references.
- **Local dev**: `op run --env-file=.env.tpl -- uv run ...` injects secrets at
  process start without a plaintext `.env` on disk; `op://` references replace
  raw values in the template.

**What 1Password is not:** a signing service. It has no API to perform a
signature with a stored key - any consumer (`op` CLI, SDK, Connect server)
*releases the secret* to the calling process, so the key still materializes in
that process's memory. The one exception proves the rule: the 1Password
[SSH agent](https://developer.1password.com/docs/ssh/agent/) signs SSH
challenges inside the 1Password app so the key never reaches the client - but
it speaks only the SSH agent protocol, not arbitrary secp256k1/EIP-712 message
signing. So: 1Password for storage and injection of API-key-class secrets,
paired with a real signer for private keys.

## Signing layer: keys that cannot be read, only asked

The KMS-style goal: order flows request a *signature* from a boundary that
holds the key; nothing on the application side can read the key itself.

Options, in ascending order of operational weight:

1. **Cloud KMS (DIY)** - AWS KMS supports the Ethereum curve natively
   (`ECC_SECG_P256K1`, non-exportable, optionally imported via BYOK; GCP and
   Azure have equivalents). Libraries such as
   [`ethereum-kms-signer`](https://github.com/meetmangukiya/ethereum-kms-signer)
   adapt it to web3.py-style signing. Cost is roughly $1/key/month plus
   fractions of a cent per signature. IAM scopes who may request signatures;
   CloudTrail logs every one.
2. **Web3Signer (self-hosted)** -
   [Consensys Web3Signer](https://github.com/Consensys/web3signer) is an open
   source remote-signing microservice: the app POSTs a payload, the service
   signs with keys backed by KMS/HSM/Vault. A ready-made "signing server" if we
   prefer an HTTP boundary over embedding KMS calls.
3. **Managed wallet infrastructure** - purpose-built for exactly the agent
   use case: [Turnkey](https://www.turnkey.com/) (keys in TEEs behind a
   programmable policy engine), [Privy](https://privy.io/) server wallets,
   [Coinbase CDP](https://docs.cdp.coinbase.com/) server wallets / AgentKit,
   [Fireblocks](https://www.fireblocks.com/) (MPC with quorum policies,
   institutional weight), and since July 2026
   [Ledger Agent Stack](https://www.coindesk.com/tech/2026/07/15/ledger-wants-ai-agents-to-manage-crypto-without-holding-your-keys)
   ("agents propose, humans approve" with hardware enforcement). This is the
   dominant industry pattern for AI-agent trading: the agent holds a scoped
   API credential, the platform holds the key, and a policy engine - not the
   prompt - decides what may be signed.
4. **Venue-native delegation** - sidestep raw keys where the venue allows:
   Polymarket's Builder profile places orders with API credentials and holds no
   private key. Its operator mode is NOT keyless - the hosted MCP server holds a
   `POLYMARKET_OPERATOR_KEY` that signs on behalf of every approving user
   (`polymarket_operator.py`), which is precisely why that key is in the QA
   tripwire and the first candidate to move behind a remote signer. Kalshi never
   uses an Ethereum key at all (RSA request-signing key, itself movable into a
   signer later); Predict.fun's smart-wallet mode separates the owner key from
   the deposit address. On-chain equivalents
   (Safe modules / session keys) can constrain an EOA's power if we ever hold
   positions in contracts.

## Target architecture

```
strategy / MCP tool / QA driver          (no key material, ever)
        |
        v
policy proxy                             per-request checks, independent of prompts:
  - venue + market allowlist               max notional per order and per day
  - rate limits, kill switch               full audit log of every request
        |
        v
signer backend                           KMS (phase 2) or managed TEE/MPC (phase 3)
  - holds non-exportable keys, returns signatures only
        |
        v
venue SDK / API                          receives a signed order, never a key
```

The policy proxy is the piece none of the storage tools provide and the reason
"just put the key in 1Password" is insufficient: with a raw key, *possession
is authorization*. With a signer + policy, authorization is a program we
control, scoped per credential, auditable, and revocable without a key
rotation.

## Phasing

- **Phase 0 (this PR)**: keyless QA lane with structural guarantees - E2B
  egress firewall, demo-only credentials via 1Password service account,
  production-secret tripwire in the QA driver.
- **Phase 1**: move all API-key-class secrets (Kalshi demo + prod API keys,
  builder profiles, OpenRouter) into 1Password; local dev switches to
  `op run`; delete plaintext `.env` from developer machines.
- **Phase 2**: stand up KMS-backed signing for one EOA venue (Limitless is the
  simplest single-key integration) behind a minimal policy proxy; measure
  latency; document the eth-account signer shim each venue SDK needs.
- **Phase 3**: evaluate managed infrastructure (Turnkey / Privy / CDP /
  Fireblocks) for production strategies once phase-2 latency and integration
  seams are understood; adopt if the policy engine and custody posture beat
  the DIY proxy.

## Open integration questions

- Each venue SDK (py-clob-client, opinion-clob-sdk, predict-sdk) assumes a
  local private key today; phase 2 requires a signer-object seam per SDK, and
  upstream support varies.
- Polymarket order signing is EIP-712 typed data; confirm the chosen signer
  exposes raw-digest signing (KMS does) and that py-clob-client can accept an
  external signature.
- Latency budget: market-making strategies sign on the hot path; a KMS
  round-trip (~tens of ms) is fine for taker flows but needs measurement
  against BBO-chasing quote updates.
