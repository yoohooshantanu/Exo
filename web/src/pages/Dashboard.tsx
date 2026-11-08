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
import { CosmicHero } from '@/components/CosmicHero'
import { ArrowRight, AlertTriangle, Sparkles, Orbit, Telescope, Compass } from 'lucide-react'
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
  const { data: target, isLoading: tLoading, isError: tError, refetch: refetchTarget } = usePriorityTarget()
  const { data: stats, isLoading: sLoading, isError: sError, refetch: refetchStats } = useStats()
  const { data: alerts, isError: aError, refetch: refetchAlerts } = useAlerts(8)
  const { data: taxStats, isError: taxError, refetch: refetchTax } = useTaxonomyStats()

  if (tError || sError || aError || taxError) {
    return (
      <div className="p-6">
        <ErrorCard 
          message="Failed to load dashboard data." 
          onRetry={() => { refetchTarget(); refetchStats(); refetchAlerts(); refetchTax(); }} 
        />
      </div>
    )
  }

  /* Synthesize chart data from stats */
  const totalPlanets = stats?.planets ?? 6467
  const colors = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']
  const pieData = (taxStats || []).map((t, i) => ({
    name: t.cluster_label ? t.cluster_label.toString() : 'Unknown',
    value: t.count,
    fill: colors[i % colors.length]
  }))

  const barData = stats ? [
    { category: 'Spectra', count: stats.atmospheric_spectra },
    { category: 'Molecules', count: stats.molecule_detections },
    { category: 'Anomalies', count: stats.anomaly_flags },
    { category: 'Orbits', count: stats.orbital_predictions },
    { category: 'Clusters', count: stats.taxonomy_clusters },
  ] : []

  const strips = stats ? [
    { label: 'Total Planets', val: stats.planets, desc: 'Confirmed exoplanets', icon: Telescope, color: 'text-cyan-400', glow: 'from-cyan-500/10' },
    { label: 'Orbital Predictions', val: stats.orbital_predictions, desc: 'Gap predictions this cycle', icon: Orbit, color: 'text-purple-400', glow: 'from-purple-500/10' },
    { label: 'Biosignatures', val: stats.molecule_detections, desc: 'Molecule detections', icon: Sparkles, color: 'text-emerald-400', glow: 'from-emerald-500/10' },
    { label: 'Anomaly Flags', val: stats.anomaly_flags, desc: 'Active anomaly alerts', icon: AlertTriangle, color: 'text-amber-400', glow: 'from-amber-500/10' },
  ] : []

  return (
    <div className="space-y-6 pb-12">
      {/* ── Playful Cosmic Hero ───────────────────────────────────── */}
      <CosmicHero 
        totalPlanets={totalPlanets} 
        totalSpectra={stats?.atmospheric_spectra ?? 120} 
      />

      {/* ── Priority Target Showcase ──────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        <Card className="relative overflow-hidden border border-white/10 bg-black/40 backdrop-blur-xl shadow-xl hover:border-cyan-500/30 transition-all duration-300">
          <div className="pointer-events-none absolute top-0 right-0 size-64 bg-cyan-500/5 rounded-full blur-3xl" />
          <CardContent className="p-6">
            {tLoading || !target ? (
              <div className="space-y-4">
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-14 w-80" />
                <Skeleton className="h-4 w-96" />
              </div>
            ) : (
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="relative flex size-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full size-2 bg-cyan-500"></span>
                    </span>
                    <p className="text-xs font-semibold uppercase tracking-widest text-cyan-400">
                      Top Target Candidate
                    </p>
                  </div>
                  <Link to={`/planets/${encodeURIComponent(target.planet_name)}`}>
                    <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white hover:text-cyan-300 transition-colors cursor-pointer group flex items-center gap-3">
                      <span>{target.planet_name}</span>
                      <ArrowRight className="size-5 opacity-0 -translate-x-2 transition-all group-hover:opacity-100 group-hover:translate-x-0 text-cyan-400" />
                    </h2>
                  </Link>
                  <p className="text-sm text-zinc-400 mt-2 max-w-xl">
                    Host star: <strong className="text-zinc-200">{target.hostname}</strong> &bull; {target.rationale}
                  </p>
                </div>
                
                {/* 3 Indices Badges */}
                <div className="grid grid-cols-3 gap-3 sm:gap-6 bg-white/[0.03] border border-white/10 p-3 sm:p-4 rounded-xl backdrop-blur-md">
                  <div className="text-center sm:text-right">
                    <div className="text-2xl sm:text-3xl font-bold text-cyan-400">
                      {target.observability_index != null ? target.observability_index.toFixed(1) : '—'}
                    </div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-medium mt-1">Observability</p>
                  </div>
                  <div className="text-center sm:text-right border-x border-white/10 px-2 sm:px-4">
                    <div className="text-2xl sm:text-3xl font-bold text-purple-400">
                      {target.physical_triage_index != null ? target.physical_triage_index.toFixed(1) : '—'}
                    </div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-medium mt-1">Triage</p>
                  </div>
                  <div className="text-center sm:text-right">
                    <div className="text-2xl sm:text-3xl font-bold text-emerald-400">
                      {target.characterization_index != null ? target.characterization_index.toFixed(1) : '—'}
                    </div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-medium mt-1">Characterization</p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* ── Stat Cards with Playful Hover Glow ──────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {sLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="border-white/10 bg-black/40"><CardContent className="p-5"><Skeleton className="h-16 w-full" /></CardContent></Card>
          ))
        ) : (
          strips.map((s, idx) => (
            <motion.div
              key={s.label}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.1 * idx }}
              whileHover={{ y: -4, transition: { duration: 0.2 } }}
            >
              <Card className="relative overflow-hidden border border-white/10 bg-black/40 backdrop-blur-md hover:border-white/20 transition-all shadow-lg group">
                <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${s.glow} to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
                <CardHeader className="pb-2 relative z-10">
                  <div className="flex items-center justify-between">
                    <CardDescription className="text-xs font-medium text-zinc-400">{s.label}</CardDescription>
                    <s.icon className={`size-4 ${s.color} transition-transform group-hover:scale-125 duration-300`} />
                  </div>
                  <CardTitle className="text-3xl font-extrabold tracking-tight text-white mt-1">
                    <AnimatedNumber value={s.val} decimals={0} className="text-3xl font-extrabold" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0 relative z-10">
                  <p className="text-xs text-zinc-400">{s.desc}</p>
                </CardContent>
              </Card>
            </motion.div>
          ))
        )}
      </div>

      {/* ── Charts Row ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Classification Donut Chart */}
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.3 }}
        >
          <Card className="border border-white/10 bg-black/40 backdrop-blur-md shadow-xl h-full">
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <Compass className="size-4 text-cyan-400" />
                <span>Planet Classification Taxonomy</span>
              </CardTitle>
              <CardDescription className="text-zinc-400">HDBSCAN clustered planetary classes</CardDescription>
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
                      innerRadius={65}
                      strokeWidth={2}
                      stroke="rgba(0,0,0,0.6)"
                    >
                      <Label
                        content={({ viewBox }) => {
                          if (viewBox && 'cx' in viewBox && 'cy' in viewBox) {
                            return (
                              <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                                <tspan x={viewBox.cx} y={viewBox.cy} className="fill-white text-2xl font-bold">
                                  {totalPlanets.toLocaleString()}
                                </tspan>
                                <tspan x={viewBox.cx} y={(viewBox.cy || 0) + 20} className="fill-zinc-400 text-xs">
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
          </Card>
        </motion.div>

        {/* Pipeline Bar Chart */}
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.35 }}
        >
          <Card className="border border-white/10 bg-black/40 backdrop-blur-md shadow-xl h-full">
            <CardHeader>
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <Sparkles className="size-4 text-purple-400" />
                <span>Detection &amp; Analytics Pipeline</span>
              </CardTitle>
              <CardDescription className="text-zinc-400">Active intelligence data records</CardDescription>
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
                      tick={{ fontSize: 12, fill: '#a1a1aa' }}
                    />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Bar dataKey="count" fill="url(#barGradient)" radius={[0, 6, 6, 0]} />
                    <defs>
                      <linearGradient id="barGradient" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#06b6d4" />
                        <stop offset="100%" stopColor="#a855f7" />
                      </linearGradient>
                    </defs>
                  </BarChart>
                </ChartContainer>
              ) : (
                <Skeleton className="h-[260px] w-full" />
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* ── Recent Alerts Table ──────────────────────────────────────── */}
      <Card className="border border-white/10 bg-black/40 backdrop-blur-md shadow-xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm font-semibold text-white">Recent Alerts &amp; Discoveries</CardTitle>
              <CardDescription className="text-zinc-400">Autonomous anomaly alerts and telemetry signals</CardDescription>
            </div>
            <Link to="/alerts" className="text-xs text-cyan-400 hover:text-cyan-300 font-medium transition-colors flex items-center gap-1 group">
              <span>View all alerts</span>
              <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader className="border-white/10">
              <TableRow className="border-white/10 hover:bg-transparent">
                <TableHead className="text-zinc-400">Timestamp</TableHead>
                <TableHead className="text-zinc-400">Type</TableHead>
                <TableHead className="text-zinc-400">Planet</TableHead>
                <TableHead className="text-right text-zinc-400">
                  <Tooltip>
                    <TooltipTrigger asChild><span className="cursor-help border-b border-dotted border-zinc-500">Score</span></TooltipTrigger>
                    <TooltipContent><p>Latest composite habitability score</p></TooltipContent>
                  </Tooltip>
                </TableHead>
                <TableHead className="w-8"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(!alerts || alerts.length === 0) ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-zinc-400 py-8">
                    No recent alerts detected
                  </TableCell>
                </TableRow>
              ) : (
                alerts.map((alert) => {
                  const isCritical = alert.severity === 'high'
                  return (
                    <TableRow key={`${alert.planet_name}-${alert.alert_type}-${alert.created_at}`} className="border-white/5 hover:bg-white/[0.04] transition-colors">
                      <TableCell className="font-mono text-xs text-zinc-400">
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
                          className="text-sm font-medium text-zinc-200 hover:text-cyan-400 transition-colors"
                        >
                          {alert.planet_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm text-cyan-400">
                        {alert.score?.toFixed(3) ?? '—'}
                      </TableCell>
                      <TableCell>
                        {isCritical && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <AlertTriangle className="w-3.5 h-3.5 text-rose-500 cursor-help outline-none animate-pulse" />
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
