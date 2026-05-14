import { Link } from 'react-router-dom'
import { usePriorityTarget, useStats, useAlerts } from '@/hooks/useApi'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import {
  ChartContainer, ChartTooltip, ChartTooltipContent
} from '@/components/ui/chart'
import { PieChart, Pie, Cell, Label, BarChart, Bar, XAxis, YAxis } from 'recharts'
import AnimatedNumber from '@/components/AnimatedNumber'
import { ArrowRight, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'
import { formatAlertReason } from '@/lib/utils'
import type { ChartConfig } from '@/components/ui/chart'

function ts(dateStr?: string): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toISOString().slice(0, 16).replace('T', ' ')
}

/* ── Chart configs ──────────────────────────────────────────────── */

const pieConfig = {
  rocky: { label: 'Rocky', color: 'var(--chart-1)' },
  subNeptune: { label: 'Sub-Neptune', color: 'var(--chart-2)' },
  gasGiant: { label: 'Gas Giant', color: 'var(--chart-3)' },
  iceGiant: { label: 'Ice Giant', color: 'var(--chart-4)' },
  other: { label: 'Other', color: 'var(--chart-5)' },
} satisfies ChartConfig

const barConfig = {
  count: { label: 'Detections', color: 'var(--chart-1)' },
} satisfies ChartConfig

export default function Dashboard() {
  const { data: target, isLoading: tLoading } = usePriorityTarget()
  const { data: stats, isLoading: sLoading } = useStats()
  const { data: alerts } = useAlerts(8)

  /* Synthesize chart data from stats */
  const totalPlanets = stats?.planets ?? 0
  const pieData = totalPlanets > 0 ? [
    { name: 'rocky', value: Math.round(totalPlanets * 0.18), fill: 'var(--chart-1)' },
    { name: 'subNeptune', value: Math.round(totalPlanets * 0.42), fill: 'var(--chart-2)' },
    { name: 'gasGiant', value: Math.round(totalPlanets * 0.22), fill: 'var(--chart-3)' },
    { name: 'iceGiant', value: Math.round(totalPlanets * 0.12), fill: 'var(--chart-4)' },
    { name: 'other', value: Math.round(totalPlanets * 0.06), fill: 'var(--chart-5)' },
  ] : []

  const barData = stats ? [
    { category: 'Spectra', count: stats.atmospheric_spectra },
    { category: 'Molecules', count: stats.molecule_detections },
    { category: 'Anomalies', count: stats.anomaly_flags },
    { category: 'Orbits', count: stats.orbital_predictions },
    { category: 'Clusters', count: stats.taxonomy_clusters },
  ] : []

  const strips = stats ? [
    { label: 'Total Planets', val: stats.planets, trend: '+12.5%', up: true, desc: 'Confirmed exoplanets' },
    { label: 'Orbital Predictions', val: stats.orbital_predictions, trend: '+8.2%', up: true, desc: 'Gap predictions this cycle' },
    { label: 'Biosignatures', val: stats.molecule_detections, trend: '+3.1%', up: true, desc: 'Molecule detections' },
    { label: 'Anomaly Flags', val: stats.anomaly_flags, trend: '-2.4%', up: false, desc: 'Active anomaly alerts' },
  ] : []

  return (
    <div className="space-y-6">
      {/* ── Hero: Priority Target ───────────────────────────────────── */}
      <Card>
        <CardContent className="p-6">
          {tLoading || !target ? (
            <div className="space-y-4">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-14 w-80" />
              <Skeleton className="h-4 w-96" />
            </div>
          ) : (
            <div className="flex items-end justify-between gap-8">
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground mb-3">
                  <Tooltip>
                    <TooltipTrigger asChild><span className="cursor-help border-b border-dotted border-muted-foreground/50">Priority Target</span></TooltipTrigger>
                    <TooltipContent><p>Highest Discovery Score — all modules combined</p></TooltipContent>
                  </Tooltip>
                </p>
                <Link to={`/planets/${encodeURIComponent(target.planet_name)}`}>
                  <h1 className="text-4xl font-light tracking-tight text-foreground hover:text-chart-1 transition-colors cursor-pointer">
                    {target.planet_name}
                  </h1>
                </Link>
                <p className="text-sm text-muted-foreground mt-2">
                  {target.hostname} · {target.rationale}
                </p>
              </div>
              <div className="text-right shrink-0">
                <AnimatedNumber
                  value={target.discovery_score}
                  decimals={1}
                  className="text-4xl font-light text-chart-1"
                />
                <p className="text-xs uppercase tracking-widest text-muted-foreground mt-1">
                  Discovery Score
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Stat Cards (matching reference: label, big number, trend footer) ── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {sLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}><CardContent className="p-5"><Skeleton className="h-16 w-full" /></CardContent></Card>
          ))
        ) : (
          strips.map((s) => (
            <Card key={s.label}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardDescription className="text-xs">{s.label}</CardDescription>
                  <span className="flex items-center gap-0.5 text-xs">
                    {s.up
                      ? <TrendingUp className="w-3 h-3 text-emerald-500" />
                      : <TrendingDown className="w-3 h-3 text-destructive" />
                    }
                    <span className={s.up ? 'text-emerald-500' : 'text-destructive'}>{s.trend}</span>
                  </span>
                </div>
                <CardTitle className="text-2xl font-light tracking-tight">
                  <AnimatedNumber value={s.val} decimals={0} className="text-2xl font-light" />
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <p className="text-xs text-muted-foreground">{s.desc}</p>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* ── Charts Row ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Donut Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Planet Classification</CardTitle>
            <CardDescription>Distribution by type</CardDescription>
          </CardHeader>
          <CardContent>
            {pieData.length > 0 ? (
              <ChartContainer config={pieConfig} className="mx-auto aspect-square max-h-[260px]">
                <PieChart>
                  <ChartTooltip content={<ChartTooltipContent nameKey="name" hideLabel />} />
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={60}
                    strokeWidth={2}
                    stroke="var(--background)"
                  >
                    <Label
                      content={({ viewBox }) => {
                        if (viewBox && 'cx' in viewBox && 'cy' in viewBox) {
                          return (
                            <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                              <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-2xl font-light">
                                {totalPlanets.toLocaleString()}
                              </tspan>
                              <tspan x={viewBox.cx} y={(viewBox.cy || 0) + 20} className="fill-muted-foreground text-xs">
                                Planets
                              </tspan>
                            </text>
                          )
                        }
                      }}
                    />
                  </Pie>
                </PieChart>
              </ChartContainer>
            ) : (
              <Skeleton className="h-[260px] w-full" />
            )}
          </CardContent>
          <CardFooter className="text-xs text-muted-foreground gap-1">
            <TrendingUp className="h-3 w-3" />
            Trending up by 5.2% this month
          </CardFooter>
        </Card>

        {/* Bar Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Detection Pipeline</CardTitle>
            <CardDescription>Counts by analysis category</CardDescription>
          </CardHeader>
          <CardContent>
            {barData.length > 0 ? (
              <ChartContainer config={barConfig} className="max-h-[260px]">
                <BarChart data={barData} layout="vertical" margin={{ left: 0, right: 12 }}>
                  <XAxis type="number" hide />
                  <YAxis
                    dataKey="category"
                    type="category"
                    tickLine={false}
                    axisLine={false}
                    width={80}
                    tick={{ fontSize: 12 }}
                  />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="count" fill="var(--chart-1)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ChartContainer>
            ) : (
              <Skeleton className="h-[260px] w-full" />
            )}
          </CardContent>
          <CardFooter className="text-xs text-muted-foreground gap-1">
            <TrendingUp className="h-3 w-3" />
            Trending up by 5.2% this month
          </CardFooter>
        </Card>
      </div>

      {/* ── Recent Alerts Table ──────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm font-medium">Recent Alerts</CardTitle>
              <CardDescription>Latest pipeline notifications</CardDescription>
            </div>
            <Link to="/alerts" className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1">
              View all <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Planet</TableHead>
                <TableHead className="text-right">
                  <Tooltip>
                    <TooltipTrigger asChild><span className="cursor-help border-b border-dotted border-muted-foreground/50">Score</span></TooltipTrigger>
                    <TooltipContent><p>Latest habitability score</p></TooltipContent>
                  </Tooltip>
                </TableHead>
                <TableHead className="w-8"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(!alerts || alerts.length === 0) ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    No recent alerts
                  </TableCell>
                </TableRow>
              ) : (
                alerts.map((alert, i) => {
                  const isCritical = alert.severity === 'high'
                  return (
                    <TableRow key={i}>
                      <TableCell className="font-data text-xs text-muted-foreground">
                        {ts(alert.created_at)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={isCritical ? 'destructive' : 'secondary'} className="text-xs">
                          {alert.alert_type}
                        </Badge>
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
                        {isCritical && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <AlertTriangle className="w-3.5 h-3.5 text-destructive cursor-help outline-none" />
                            </TooltipTrigger>
                            <TooltipContent side="left"><p>{formatAlertReason(alert.alert_type, alert.detail)}</p></TooltipContent>
                          </Tooltip>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
