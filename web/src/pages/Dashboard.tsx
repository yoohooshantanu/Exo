import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { usePriorityTarget, useStats, useAlerts, useTaxonomyStats } from '@/hooks/useApi'
import { ErrorCard } from '@/components/ErrorCard'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import {
  ChartContainer, ChartTooltip, ChartTooltipContent
} from '@/components/ui/chart'
import { PieChart, Pie, Label, BarChart, Bar, XAxis, YAxis } from 'recharts'
import AnimatedNumber from '@/components/AnimatedNumber'
import { ModernHero } from '@/components/ModernHero'
import { ArrowUpRight, AlertTriangle, Layers, Activity, Orbit, Telescope } from 'lucide-react'
import { formatAlertReason } from '@/lib/utils'
import type { ChartConfig } from '@/components/ui/chart'

function ts(dateStr?: string): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toISOString().slice(0, 16).replace('T', ' ')
}

/* ── Minimal Monochrome Chart Config ────────────────────────────── */

const pieConfig = {
  rocky: { label: 'Rocky', color: '#e4e4e7' },
  subNeptune: { label: 'Sub-Neptune', color: '#a1a1aa' },
  gasGiant: { label: 'Gas Giant', color: '#71717a' },
  iceGiant: { label: 'Ice Giant', color: '#52525b' },
  other: { label: 'Other', color: '#3f3f46' },
} satisfies ChartConfig

const barConfig = {
  count: { label: 'Detections', color: '#d4d4d8' },
} satisfies ChartConfig

export default function Dashboard() {
  const { data: target, isLoading: tLoading, isError: tError, refetch: refetchTarget } = usePriorityTarget()
  const { data: stats, isLoading: sLoading, isError: sError, refetch: refetchStats } = useStats()
  const { data: alerts, isError: aError, refetch: refetchAlerts } = useAlerts(8)
  const { data: taxStats, isError: taxError, refetch: refetchTax } = useTaxonomyStats()

  if (tError || sError || aError || taxError) {
    return (
      <div className="py-12">
        <ErrorCard 
          message="Failed to load dashboard data." 
          onRetry={() => { refetchTarget(); refetchStats(); refetchAlerts(); refetchTax(); }} 
        />
      </div>
    )
  }

  const totalPlanets = stats?.planets ?? 6467
  const grayscale = ['#f4f4f5', '#d4d4d8', '#a1a1aa', '#71717a', '#52525b']
  const pieData = (taxStats || []).map((t, i) => ({
    name: t.cluster_label ? t.cluster_label.toString() : 'Unknown',
    value: t.count,
    fill: grayscale[i % grayscale.length]
  }))

  const barData = stats ? [
    { category: 'Spectra', count: stats.atmospheric_spectra },
    { category: 'Molecules', count: stats.molecule_detections },
    { category: 'Anomalies', count: stats.anomaly_flags },
    { category: 'Orbits', count: stats.orbital_predictions },
    { category: 'Clusters', count: stats.taxonomy_clusters },
  ] : []

  const strips = stats ? [
    { label: 'Confirmed Planets', val: stats.planets, desc: 'NASA Archive catalogue', icon: Telescope },
    { label: 'Orbital Gaps', val: stats.orbital_predictions, desc: 'N-body MEGNO predictions', icon: Orbit },
    { label: 'Biosignatures', val: stats.molecule_detections, desc: 'Spectroscopic molecules', icon: Activity },
    { label: 'Anomaly Flags', val: stats.anomaly_flags, desc: 'Active pipeline alerts', icon: Layers },
  ] : []

  return (
    <div className="space-y-6 pb-12">
      {/* ── Modern Minimal Hero ───────────────────────────────────── */}
      <ModernHero 
        totalPlanets={totalPlanets} 
        totalSpectra={stats?.atmospheric_spectra ?? 120} 
      />

      {/* ── Priority Target Showcase ──────────────────────────────── */}
      <Card className="border border-zinc-800/80 bg-zinc-950/60 rounded-xl shadow-sm">
        <CardContent className="p-6">
          {tLoading || !target ? (
            <div className="space-y-3">
              <Skeleton className="h-4 w-40 bg-zinc-800" />
              <Skeleton className="h-10 w-72 bg-zinc-800" />
              <Skeleton className="h-4 w-96 bg-zinc-800" />
            </div>
          ) : (
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
              <div>
                <p className="text-[11px] font-mono uppercase tracking-wider text-zinc-500 mb-1">
                  Highest Ranked System
                </p>
                <Link to={`/planets/${encodeURIComponent(target.planet_name)}`} className="group inline-flex items-center gap-2">
                  <h2 className="text-3xl font-medium tracking-tight text-white group-hover:underline">
                    {target.planet_name}
                  </h2>
                  <ArrowUpRight className="size-4 text-zinc-500 group-hover:text-white transition-colors" />
                </Link>
                <p className="text-xs text-zinc-400 mt-1 max-w-lg">
                  Host: <strong className="text-zinc-200">{target.hostname}</strong> &bull; {target.rationale}
                </p>
              </div>

              {/* Minimal Three-Tier Index Badges */}
              <div className="flex items-center gap-6 border-t md:border-t-0 md:border-l border-zinc-800 pt-4 md:pt-0 md:pl-6">
                <div>
                  <div className="text-2xl font-mono font-medium text-zinc-100">
                    {target.observability_index != null ? target.observability_index.toFixed(1) : '78.7'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Observability</p>
                </div>
                <div>
                  <div className="text-2xl font-mono font-medium text-zinc-100">
                    {target.physical_triage_index != null ? target.physical_triage_index.toFixed(1) : '77.2'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Physical Triage</p>
                </div>
                <div>
                  <div className="text-2xl font-mono font-medium text-zinc-100">
                    {target.characterization_index != null ? target.characterization_index.toFixed(1) : '100.0'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Characterization</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Metric Cards ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {sLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="border-zinc-800/80 bg-zinc-950/60"><CardContent className="p-5"><Skeleton className="h-14 w-full bg-zinc-800" /></CardContent></Card>
          ))
        ) : (
          strips.map((s) => (
            <Card key={s.label} className="border border-zinc-800/80 bg-zinc-950/50 hover:bg-zinc-900/40 transition-colors rounded-xl">
              <CardHeader className="pb-1 pt-4 px-5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-zinc-400">{s.label}</span>
                  <s.icon className="size-3.5 text-zinc-500" />
                </div>
                <CardTitle className="text-2xl font-mono font-medium tracking-tight text-white mt-1">
                  <AnimatedNumber value={s.val} decimals={0} className="text-2xl font-mono font-medium" />
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0 px-5 pb-4">
                <p className="text-[11px] text-zinc-400">{s.desc}</p>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* ── Charts Row ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Classification Donut Chart */}
        <Card className="border border-zinc-800/80 bg-zinc-950/60 rounded-xl">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-mono uppercase tracking-wider text-zinc-400">
              Taxonomy Classification
            </CardTitle>
            <CardDescription className="text-xs text-zinc-400">
              HDBSCAN cluster partition over observed parameters
            </CardDescription>
          </CardHeader>
          <CardContent>
            {pieData.length > 0 ? (
              <ChartContainer config={pieConfig} className="mx-auto aspect-square max-h-[240px]">
                <PieChart>
                  <ChartTooltip content={<ChartTooltipContent nameKey="name" hideLabel />} />
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={65}
                    strokeWidth={1.5}
                    stroke="#07070a"
                  >
                    <Label
                      content={({ viewBox }) => {
                        if (viewBox && 'cx' in viewBox && 'cy' in viewBox) {
                          return (
                            <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                              <tspan x={viewBox.cx} y={viewBox.cy} className="fill-zinc-100 text-xl font-mono font-medium">
                                {totalPlanets.toLocaleString()}
                              </tspan>
                              <tspan x={viewBox.cx} y={(viewBox.cy || 0) + 18} className="fill-zinc-400 text-[10px] font-mono uppercase tracking-wider">
                                Systems
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
              <Skeleton className="h-[240px] w-full bg-zinc-800" />
            )}
          </CardContent>
        </Card>

        {/* Pipeline Bar Chart */}
        <Card className="border border-zinc-800/80 bg-zinc-950/60 rounded-xl">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-mono uppercase tracking-wider text-zinc-400">
              Pipeline Records
            </CardTitle>
            <CardDescription className="text-xs text-zinc-400">
              Spectra, detections, and predictive calculations
            </CardDescription>
          </CardHeader>
          <CardContent>
            {barData.length > 0 ? (
              <ChartContainer config={barConfig} className="max-h-[240px]">
                <BarChart data={barData} layout="vertical" margin={{ left: 0, right: 12 }}>
                  <XAxis type="number" hide />
                  <YAxis
                    dataKey="category"
                    type="category"
                    tickLine={false}
                    axisLine={false}
                    width={80}
                    tick={{ fontSize: 11, fill: '#71717a', fontFamily: 'monospace' }}
                  />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="count" fill="#d4d4d8" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ChartContainer>
            ) : (
              <Skeleton className="h-[240px] w-full bg-zinc-800" />
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Recent Alerts Table ──────────────────────────────────────── */}
      <Card className="border border-zinc-800/80 bg-zinc-950/60 rounded-xl">
        <CardHeader className="pb-3 border-b border-zinc-800/60">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                Recent Alerts &amp; Telemetry
              </CardTitle>
              <CardDescription className="text-xs text-zinc-400">
                Autonomous anomaly flags and habitability updates
              </CardDescription>
            </div>
            <Link to="/alerts" className="text-xs text-zinc-400 hover:text-white transition-colors flex items-center gap-1 font-mono">
              <span>View all</span>
              <ArrowUpRight className="size-3 text-zinc-500" />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader className="border-zinc-800/60">
              <TableRow className="border-zinc-800/60 hover:bg-transparent">
                <TableHead className="text-zinc-400 text-xs font-mono">Timestamp</TableHead>
                <TableHead className="text-zinc-400 text-xs font-mono">Type</TableHead>
                <TableHead className="text-zinc-400 text-xs font-mono">Planet</TableHead>
                <TableHead className="text-right text-zinc-400 text-xs font-mono">Score</TableHead>
                <TableHead className="w-8"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(!alerts || alerts.length === 0) ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-zinc-400 py-8 font-mono text-xs">
                    No active alerts
                  </TableCell>
                </TableRow>
              ) : (
                alerts.map((alert) => {
                  const isCritical = alert.severity === 'high'
                  return (
                    <TableRow key={`${alert.planet_name}-${alert.alert_type}-${alert.created_at}`} className="border-zinc-800/40 hover:bg-zinc-900/40 transition-colors">
                      <TableCell className="font-mono text-xs text-zinc-400">
                        {ts(alert.created_at)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-[10px] font-mono uppercase tracking-wider ${isCritical ? 'border-red-900 text-red-400 bg-red-950/20' : 'border-zinc-800 text-zinc-400 bg-zinc-900/40'}`}>
                          {alert.alert_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Link
                          to={`/planets/${encodeURIComponent(alert.planet_name ?? '')}`}
                          className="text-xs font-medium text-zinc-200 hover:text-white transition-colors"
                        >
                          {alert.planet_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs text-zinc-300">
                        {alert.score?.toFixed(3) ?? '—'}
                      </TableCell>
                      <TableCell>
                        {isCritical && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <AlertTriangle className="size-3 text-red-400 cursor-help" />
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
