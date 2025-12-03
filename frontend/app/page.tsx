"use client"

import { useState } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BalancesCard } from "@/components/balances-card"
import { PositionsTable } from "@/components/positions-table"
import { OrdersTable } from "@/components/orders-table"
import { MarketsTable } from "@/components/markets-table"
import { useApiData } from "@/hooks/use-api-data"
import { api } from "@/lib/api"

export default function Dashboard() {
  const [refreshInterval, setRefreshInterval] = useState(5000)

  const { data: exchanges, loading: exchangesLoading } = useApiData(
    () => api.getExchanges(),
    refreshInterval
  )

  const { data: balances, loading: balancesLoading, refetch: refetchBalances } = useApiData(
    () => api.getBalances(),
    refreshInterval
  )

  const { data: positions, loading: positionsLoading, refetch: refetchPositions } = useApiData(
    () => api.getPositions(),
    refreshInterval
  )

  const { data: orders, loading: ordersLoading, refetch: refetchOrders } = useApiData(
    () => api.getOrders(),
    refreshInterval
  )

  const { data: markets, loading: marketsLoading, refetch: refetchMarkets } = useApiData(
    () => api.getMarkets(undefined, 20),
    refreshInterval
  )

  const handleRefreshAll = () => {
    refetchBalances()
    refetchPositions()
    refetchOrders()
    refetchMarkets()
  }

  const enabledExchanges = exchanges?.filter(e => e.enabled) || []

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Dr Manhattan Debug Dashboard</h1>
            <p className="text-muted-foreground mt-1">
              Monitor positions, balances, orders, and markets across prediction market exchanges
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleRefreshAll} variant="outline">
              Refresh All
            </Button>
          </div>
        </div>

        <div className="flex gap-2">
          {exchangesLoading ? (
            <Badge variant="outline">Loading exchanges...</Badge>
          ) : (
            enabledExchanges.map(exchange => (
              <Badge key={exchange.id} className="capitalize">
                {exchange.name}
              </Badge>
            ))
          )}
          {!exchangesLoading && enabledExchanges.length === 0 && (
            <Badge variant="destructive">No exchanges configured</Badge>
          )}
        </div>

        <Tabs defaultValue="overview" className="space-y-4">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="positions">Positions</TabsTrigger>
            <TabsTrigger value="orders">Orders</TabsTrigger>
            <TabsTrigger value="markets">Markets</TabsTrigger>
            {enabledExchanges.map(exchange => (
              <TabsTrigger key={exchange.id} value={exchange.id}>
                {exchange.name}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {balancesLoading ? (
                <div className="col-span-1">Loading balances...</div>
              ) : balances && balances.length > 0 ? (
                <BalancesCard balances={balances} />
              ) : (
                <div className="col-span-1 p-4 border rounded-lg">No balances data</div>
              )}
            </div>

            {positionsLoading ? (
              <div>Loading positions...</div>
            ) : positions && positions.length > 0 ? (
              <PositionsTable positions={positions} />
            ) : (
              <div className="p-4 border rounded-lg text-center text-muted-foreground">
                No positions data
              </div>
            )}

            {ordersLoading ? (
              <div>Loading orders...</div>
            ) : orders && orders.length > 0 ? (
              <OrdersTable orders={orders} />
            ) : (
              <div className="p-4 border rounded-lg text-center text-muted-foreground">
                No orders data
              </div>
            )}
          </TabsContent>

          <TabsContent value="positions">
            {positionsLoading ? (
              <div>Loading positions...</div>
            ) : positions ? (
              <PositionsTable positions={positions} />
            ) : (
              <div className="p-4 border rounded-lg text-center text-muted-foreground">
                No positions data
              </div>
            )}
          </TabsContent>

          <TabsContent value="orders">
            {ordersLoading ? (
              <div>Loading orders...</div>
            ) : orders ? (
              <OrdersTable orders={orders} />
            ) : (
              <div className="p-4 border rounded-lg text-center text-muted-foreground">
                No orders data
              </div>
            )}
          </TabsContent>

          <TabsContent value="markets">
            {marketsLoading ? (
              <div>Loading markets...</div>
            ) : markets ? (
              <MarketsTable markets={markets} />
            ) : (
              <div className="p-4 border rounded-lg text-center text-muted-foreground">
                No markets data
              </div>
            )}
          </TabsContent>

          {enabledExchanges.map(exchange => (
            <TabsContent key={exchange.id} value={exchange.id} className="space-y-4">
              <h2 className="text-2xl font-bold capitalize">{exchange.name} Exchange</h2>

              {balances && (
                <BalancesCard
                  balances={balances.filter(b => b.exchange === exchange.id)}
                />
              )}

              {positions && (
                <PositionsTable
                  positions={positions.filter(p => p.exchange === exchange.id)}
                />
              )}

              {orders && (
                <OrdersTable
                  orders={orders.filter(o => o.exchange === exchange.id)}
                />
              )}

              {markets && (
                <MarketsTable
                  markets={markets.filter(m => m.exchange === exchange.id)}
                />
              )}
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </div>
  )
}
