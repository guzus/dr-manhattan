import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Prediction Market Trading Bot',
  description: 'AI Agent Trading Bot for Prediction Markets',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-[#0a0b0d] text-white antialiased">{children}</body>
    </html>
  )
}
