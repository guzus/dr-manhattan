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
import { OrderResponse } from "@/lib/types"

interface OrdersTableProps {
  orders: OrderResponse[]
}

export function OrdersTable({ orders }: OrdersTableProps) {
  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'open':
        return 'bg-blue-500/10 text-blue-600 border-blue-500/20'
      case 'filled':
        return 'bg-green-500/10 text-green-600 border-green-500/20'
      case 'partially_filled':
        return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20'
      case 'cancelled':
        return 'bg-gray-500/10 text-gray-600 border-gray-500/20'
      case 'rejected':
        return 'bg-red-500/10 text-red-600 border-red-500/20'
      default:
        return 'bg-gray-500/10 text-gray-600 border-gray-500/20'
    }
  }

  const getSideColor = (side: string) => {
    return side.toLowerCase() === 'buy'
      ? 'bg-green-500/10 text-green-600 border-green-500/20'
      : 'bg-red-500/10 text-red-600 border-red-500/20'
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Open Orders</CardTitle>
        <CardDescription>Currently active orders across all exchanges</CardDescription>
      </CardHeader>
      <CardContent>
        {orders.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">No open orders</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Order ID</TableHead>
                  <TableHead>Market ID</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead className="text-right">Filled</TableHead>
                  <TableHead className="text-right">Remaining</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.map((order) => {
                  const remaining = order.size - order.filled
                  const fillPercentage = (order.filled / order.size) * 100

                  return (
                    <TableRow key={order.id}>
                      <TableCell>
                        <Badge variant="outline" className="capitalize">
                          {order.exchange}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs max-w-[100px] truncate">
                        {order.id}
                      </TableCell>
                      <TableCell className="font-mono text-xs max-w-[100px] truncate">
                        {order.market_id}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{order.outcome}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={getSideColor(order.side)}>
                          {order.side.toUpperCase()}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">${order.price.toFixed(4)}</TableCell>
                      <TableCell className="text-right">{order.size.toFixed(2)}</TableCell>
                      <TableCell className="text-right">
                        {order.filled.toFixed(2)}
                        {order.filled > 0 && (
                          <span className="text-xs text-muted-foreground ml-1">
                            ({fillPercentage.toFixed(0)}%)
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{remaining.toFixed(2)}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={getStatusColor(order.status)}>
                          {order.status.replace('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(order.created_at).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
