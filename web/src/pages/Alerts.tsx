import { Link } from 'react-router-dom'
import { useAlerts } from '@/hooks/useApi'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import { AlertTriangle } from 'lucide-react'

function ts(dateStr?: string): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toISOString().slice(0, 16).replace('T', ' ')
}

export default function Alerts() {
  const { data: alerts, isLoading } = useAlerts(100)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-medium tracking-tight">Alerts Feed</h1>
          <p className="text-sm text-muted-foreground mt-1">Real-time pipeline notifications</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-chart-1 animate-pulse" />
          <span className="font-data text-xs text-muted-foreground">
            {alerts?.length ?? 0} alerts
          </span>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">All Alerts</CardTitle>
          <CardDescription>Sorted by most recent</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Timestamp</TableHead>
                <TableHead className="text-xs">Severity</TableHead>
                <TableHead className="text-xs">Type</TableHead>
                <TableHead className="text-xs">Planet</TableHead>
                <TableHead className="text-xs text-right">Score</TableHead>
                <TableHead className="text-xs w-8"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && Array.from({ length: 8 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                  ))}
                </TableRow>
              ))}

              {alerts?.map((alert, i) => {
                const isCritical = alert.severity === 'high'
                return (
                  <TableRow key={i}>
                    <TableCell className="font-data text-xs text-muted-foreground">
                      {ts(alert.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={isCritical ? 'destructive' : 'secondary'} className="text-xs">
                        {alert.severity}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {alert.detail || alert.alert_type}
                    </TableCell>
                    <TableCell>
                      <Link
                        to={`/planets/${encodeURIComponent(alert.planet_name ?? '')}`}
                        className="text-sm text-foreground hover:text-chart-1 transition-colors"
                      >
                        {alert.planet_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right font-data text-sm text-chart-1">
                      {alert.score?.toFixed(3) ?? '—'}
                    </TableCell>
                    <TableCell>
                      {isCritical && <AlertTriangle className="w-3.5 h-3.5 text-destructive" />}
                    </TableCell>
                  </TableRow>
                )
              })}

              {!alerts?.length && !isLoading && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    No alerts. System nominal.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
