"use client"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { PositionResponse } from "@/lib/types"

interface PositionsTableProps {
  positions: PositionResponse[]
}

export function PositionsTable({ positions }: PositionsTableProps) {
  const totalPnL = positions.reduce((sum, pos) => sum + pos.unrealized_pnl, 0)
  const totalValue = positions.reduce((sum, pos) => sum + pos.current_value, 0)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Positions</CardTitle>
            <CardDescription>Current open positions across all exchanges</CardDescription>
          </div>
          <div className="text-right">
            <p className="text-sm text-muted-foreground">Total Value</p>
            <p className="text-2xl font-bold">${totalValue.toFixed(2)}</p>
            <p className={`text-sm font-medium ${totalPnL >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {totalPnL >= 0 ? '+' : ''}{totalPnL.toFixed(2)} ({((totalPnL / (totalValue - totalPnL)) * 100).toFixed(2)}%)
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">No open positions</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Market ID</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead className="text-right">Avg Price</TableHead>
                  <TableHead className="text-right">Current Price</TableHead>
                  <TableHead className="text-right">Cost Basis</TableHead>
                  <TableHead className="text-right">Current Value</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                  <TableHead className="text-right">PnL %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((position, idx) => (
                  <TableRow key={`${position.exchange}-${position.market_id}-${position.outcome}-${idx}`}>
                    <TableCell>
                      <Badge variant="outline" className="capitalize">
                        {position.exchange}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs max-w-[100px] truncate">
                      {position.market_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{position.outcome}</Badge>
                    </TableCell>
                    <TableCell className="text-right">{position.size.toFixed(2)}</TableCell>
                    <TableCell className="text-right">${position.average_price.toFixed(4)}</TableCell>
                    <TableCell className="text-right">${position.current_price.toFixed(4)}</TableCell>
                    <TableCell className="text-right">${position.cost_basis.toFixed(2)}</TableCell>
                    <TableCell className="text-right font-medium">${position.current_value.toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-medium ${position.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {position.unrealized_pnl >= 0 ? '+' : ''}{position.unrealized_pnl.toFixed(2)}
                    </TableCell>
                    <TableCell className={`text-right font-medium ${position.unrealized_pnl_percent >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {position.unrealized_pnl_percent >= 0 ? '+' : ''}{position.unrealized_pnl_percent.toFixed(2)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
