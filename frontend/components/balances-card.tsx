"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { BalanceResponse } from "@/lib/types"

interface BalancesCardProps {
  balances: BalanceResponse[]
}

export function BalancesCard({ balances }: BalancesCardProps) {
  const totalBalance = balances.reduce((acc, b) => {
    const total = Object.values(b.balances).reduce((sum, val) => sum + val, 0)
    return acc + total
  }, 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Balances</CardTitle>
        <CardDescription>Current balances across all exchanges</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex items-center justify-between p-4 bg-muted rounded-lg">
            <div>
              <p className="text-sm font-medium text-muted-foreground">Total Balance</p>
              <p className="text-2xl font-bold">${totalBalance.toFixed(2)}</p>
            </div>
          </div>

          {balances.map((balance) => (
            <div key={balance.exchange} className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {balance.exchange}
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(balance.balances).map(([token, amount]) => (
                  <div key={token} className="flex justify-between p-2 bg-muted/50 rounded">
                    <span className="text-sm font-medium">{token}</span>
                    <span className="text-sm">{amount.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
