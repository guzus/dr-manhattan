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
import { MarketResponse } from "@/lib/types"

interface MarketsTableProps {
  markets: MarketResponse[]
}

export function MarketsTable({ markets }: MarketsTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Markets</CardTitle>
        <CardDescription>Available markets (showing first 20)</CardDescription>
      </CardHeader>
      <CardContent>
        {markets.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">No markets found</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Question</TableHead>
                  <TableHead>Outcomes</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Liquidity</TableHead>
                  <TableHead>Prices</TableHead>
                  <TableHead>Spread</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Close Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {markets.map((market) => (
                  <TableRow key={`${market.exchange}-${market.id}`}>
                    <TableCell>
                      <Badge variant="outline" className="capitalize">
                        {market.exchange}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[300px]">
                      <div className="truncate" title={market.question}>
                        {market.question}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono truncate mt-1">
                        {market.id}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {market.outcomes.map((outcome) => (
                          <Badge key={outcome} variant="secondary" className="text-xs">
                            {outcome}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">${market.volume.toFixed(0)}</TableCell>
                    <TableCell className="text-right">${market.liquidity.toFixed(0)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        {Object.entries(market.prices).map(([outcome, price]) => (
                          <div key={outcome} className="text-xs">
                            <span className="text-muted-foreground">{outcome}:</span>{' '}
                            <span className="font-medium">${price.toFixed(4)}</span>
                          </div>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      {market.spread !== null ? (
                        <span className="text-sm font-medium">{(market.spread * 100).toFixed(2)}%</span>
                      ) : (
                        <span className="text-sm text-muted-foreground">N/A</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={market.is_open ? "default" : "secondary"}>
                        {market.is_open ? "Open" : "Closed"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {market.close_time ? new Date(market.close_time).toLocaleString() : 'N/A'}
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
