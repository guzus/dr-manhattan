import { getDefaultConfig } from '@rainbow-me/rainbowkit'
import { polygon } from 'wagmi/chains'

export const config = getDefaultConfig({
  appName: 'Dr. Manhattan',
  projectId: 'a1b2c3d4e5f6', // Get from WalletConnect Cloud
  chains: [polygon],
})

// Authentication message format
export const AUTH_MESSAGE_PREFIX = 'I authorize Dr. Manhattan to trade on Polymarket on my behalf.'

// Expiry options in seconds
export const EXPIRY_OPTIONS = [
  { label: '24 hours', value: 86400 },
  { label: '7 days', value: 604800 },
  { label: '30 days', value: 2592000 },
  { label: '90 days', value: 7776000 },
] as const

export type ExpiryOption = typeof EXPIRY_OPTIONS[number]['value']

export function createAuthMessage(walletAddress: string, timestamp: number, expirySeconds: number): string {
  return `${AUTH_MESSAGE_PREFIX}

Wallet: ${walletAddress}
Timestamp: ${timestamp}
Expiry: ${expirySeconds}`
}

// Server operator address (to be updated when deployed)
export const OPERATOR_ADDRESS = '0x0000000000000000000000000000000000000000'

// CTF Contract address on Polygon
export const CTF_CONTRACT_ADDRESS = '0x4d97dcd97ec945f40cf65f87097ace5ea0476045'

// CTF Contract ABI (only setApprovalForAll)
export const CTF_ABI = [
  {
    name: 'setApprovalForAll',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'operator', type: 'address' },
      { name: 'approved', type: 'bool' },
    ],
    outputs: [],
  },
  {
    name: 'isApprovedForAll',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'operator', type: 'address' },
    ],
    outputs: [{ name: '', type: 'bool' }],
  },
] as const
