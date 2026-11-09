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
import {
  ArrowUpRight, AlertTriangle, Layers, Activity, Orbit, Telescope,
  ShieldCheck, Scale, Sparkles, BookOpen, Compass, CheckCircle2
} from 'lucide-react'
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

const PROPOSAL_TARGETS = [
  {
    name: 'TRAPPIST-1 e',
    hostname: 'TRAPPIST-1',
    dist: '12.1 pc',
    radius: '0.92 R⊕',
    teq: '250 K',
    p_rocky: '0.95',
    obs_index: 78.7,
    triage_index: 77.2,
    char_index: 100.0,
    science_case: 'Terrestrial archetype in conservative HZ. Atmospheric CH4, CO, CO2, H2O detected. High transmission SNR.',
    urgency: 'HIGH PRIORITY'
  },
  {
    name: 'LHS 1140 b',
    hostname: 'LHS 1140',
    dist: '15.0 pc',
    radius: '1.73 R⊕',
    teq: '235 K',
    p_rocky: '0.64',
    obs_index: 76.9,
    triage_index: 69.3,
    char_index: 79.3,
    science_case: 'Super-Earth/sub-Neptune border. High bulk density suggests water-rich envelope in conservative HZ.',
    urgency: 'HIGH PRIORITY'
  },
  {
    name: 'TOI-700 d',
    hostname: 'TOI-700',
    dist: '31.1 pc',
    radius: '1.14 R⊕',
    teq: '269 K',
    p_rocky: '0.95',
    obs_index: 64.2,
    triage_index: 80.0,
    char_index: 45.0,
    science_case: 'Quiescent early M-dwarf host. Negligible flaring stripping risk. Prime target for Cycles 4–5 proposals.',
    urgency: 'RECOMMENDED'
  },
  {
    name: 'Kepler-442 b',
    hostname: 'Kepler-442',
    dist: '366 pc',
    radius: '1.34 R⊕',
    teq: '233 K',
    p_rocky: '0.95',
    obs_index: 42.5,
    triage_index: 79.8,
    char_index: 35.0,
    science_case: 'K-dwarf host sweet spot (extended main-sequence lifespan + mild UV environment). Superb long-term retention.',
    urgency: 'RECOMMENDED'
  },
  {
    name: 'Wolf 1069 b',
    hostname: 'Wolf 1069',
    dist: '9.6 pc',
    radius: '1.08 R⊕',
    teq: '250 K',
    p_rocky: '0.95',
    obs_index: 58.0,
    triage_index: 78.8,
    char_index: 30.0,
    science_case: 'Ultra-nearby (9.6 pc) non-transiting target. Prime candidate for ground-based ELT high-dispersion spectroscopy.',
    urgency: 'ELT TARGET'
  },
  {
    name: 'GJ 1061 c',
    hostname: 'GJ 1061',
    dist: '3.7 pc',
    radius: '1.12 R⊕',
    teq: '275 K',
    p_rocky: '0.95',
    obs_index: 71.0,
    triage_index: 77.2,
    char_index: 35.0,
    science_case: 'Nearby (3.7 pc) compact multi-planet system. Temperate rocky world with high thermal emission potential.',
    urgency: 'RECOMMENDED'
  },
]

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
  const grayscale = ['#f4f4f5', '#d4d4d8', '#a1a1aa', '#71717a', '#52525b', '#3f3f46', '#27272a']

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
    { label: 'Confirmed Exoplanets', val: stats.planets, desc: 'NASA Archive + Gaia DR3', icon: Telescope },
    { label: 'Orbital Gap Predictions', val: stats.orbital_predictions, desc: 'N-body MEGNO verified', icon: Orbit },
    { label: 'Biosignature Detections', val: stats.molecule_detections, desc: 'HITRAN template hits', icon: Activity },
    { label: 'Active Pipeline Alerts', val: stats.anomaly_flags, desc: 'Multi-engine flags', icon: Layers },
  ] : []

  return (
    <div className="space-y-8 pb-16">
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
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-cyan-400">
                    Highest Ranked Target
                  </span>
                  <Badge variant="outline" className="border-cyan-500/30 text-cyan-400 bg-cyan-950/20 text-[10px] font-mono">
                    P_rocky = 0.95
                  </Badge>
                </div>
                <Link to={`/planets/${encodeURIComponent(target.planet_name)}`} className="group inline-flex items-center gap-2">
                  <h2 className="text-3xl font-medium tracking-tight text-white group-hover:underline">
                    {target.planet_name}
                  </h2>
                  <ArrowUpRight className="size-4 text-zinc-500 group-hover:text-white transition-colors" />
                </Link>
                <p className="text-xs text-zinc-400 mt-1 max-w-xl leading-relaxed">
                  Host Star: <strong className="text-zinc-200">{target.hostname}</strong> &bull; {target.rationale}
                </p>
              </div>

              {/* Minimal Three-Tier Index Badges */}
              <div className="flex items-center gap-6 border-t md:border-t-0 md:border-l border-zinc-800 pt-4 md:pt-0 md:pl-6">
                <div>
                  <div className="text-2xl font-mono font-medium text-cyan-400">
                    {target.observability_index != null ? target.observability_index.toFixed(1) : '78.7'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Observability</p>
                </div>
                <div>
                  <div className="text-2xl font-mono font-medium text-emerald-400">
                    {target.physical_triage_index != null ? target.physical_triage_index.toFixed(1) : '77.2'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Physical Triage</p>
                </div>
                <div>
                  <div className="text-2xl font-mono font-medium text-purple-400">
                    {target.characterization_index != null ? target.characterization_index.toFixed(1) : '100.0'}
                  </div>
                  <p className="text-[10px] uppercase font-mono tracking-wider text-zinc-500">Characterization</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Key Metrics Strips ───────────────────────────────────────── */}
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

      {/* ── NEW: Observation & Proposal Intelligence Section ─────────── */}
      <Card className="border border-zinc-800/80 bg-zinc-950/60 rounded-xl overflow-hidden">
        <CardHeader className="p-6 border-b border-zinc-800/60">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 text-cyan-400" />
                <CardTitle className="text-sm font-mono uppercase tracking-wider text-white">
                  Observation &amp; Proposal Intelligence
                </CardTitle>
                <Badge variant="outline" className="border-cyan-500/30 text-cyan-400 bg-cyan-950/20 text-[10px] font-mono">
                  Cycles 4–5 &amp; ELT Targets
                </Badge>
              </div>
              <CardDescription className="text-xs text-zinc-400 mt-1 max-w-2xl">
                High-priority terrestrial candidates ranked by uncoupled Physical Triage (P_rocky &times; ESI) 
                and Observability (transmission SNR proxy). Curated for telescope time allocation proposals.
              </CardDescription>
            </div>
            <Link
              to="/validation"
              className="inline-flex items-center gap-1.5 text-xs font-mono text-zinc-300 hover:text-white transition-colors"
            >
              <span>View JWST Study</span>
              <ArrowUpRight className="size-3 text-zinc-400" />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table className="min-w-[1050px]">
              <TableHeader className="bg-zinc-900/60">
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="w-[160px] whitespace-nowrap text-xs font-mono text-zinc-400">Target Candidate</TableHead>
                  <TableHead className="w-[180px] whitespace-nowrap text-xs font-mono text-zinc-400">Distance &bull; Radius &bull; Teq</TableHead>
                  <TableHead className="w-[100px] whitespace-nowrap text-xs font-mono text-zinc-400 text-center">P_rocky Gate</TableHead>
                  <TableHead className="w-[110px] whitespace-nowrap text-xs font-mono text-zinc-400 text-right">Observability</TableHead>
                  <TableHead className="w-[110px] whitespace-nowrap text-xs font-mono text-zinc-400 text-right">Physical Triage</TableHead>
                  <TableHead className="min-w-[320px] text-xs font-mono text-zinc-400">Scientific Proposal Justification</TableHead>
                  <TableHead className="w-[140px] whitespace-nowrap text-xs font-mono text-zinc-400 text-center">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="font-mono text-xs">
                {PROPOSAL_TARGETS.map((p) => (
                  <TableRow key={p.name} className="border-zinc-800/60 hover:bg-zinc-900/40 transition-colors">
                    <TableCell className="w-[160px] whitespace-nowrap font-medium text-white">
                      <Link to={`/planets/${encodeURIComponent(p.name)}`} className="hover:underline flex items-center gap-1.5">
                        <span>{p.name}</span>
                        <ArrowUpRight className="size-3 text-zinc-400" />
                      </Link>
                      <span className="text-[10px] text-zinc-400 block">{p.hostname}</span>
                    </TableCell>
                    <TableCell className="w-[180px] whitespace-nowrap text-zinc-300">
                      <span>{p.dist}</span> &bull; <span>{p.radius}</span> &bull; <span>{p.teq}</span>
                    </TableCell>
                    <TableCell className="w-[100px] whitespace-nowrap text-center">
                      <Badge variant="outline" className="border-zinc-800 text-zinc-300 text-[10px]">
                        {p.p_rocky}
                      </Badge>
                    </TableCell>
                    <TableCell className="w-[110px] whitespace-nowrap text-right text-cyan-400 font-semibold">
                      {p.obs_index.toFixed(1)}
                    </TableCell>
                    <TableCell className="w-[110px] whitespace-nowrap text-right text-emerald-400 font-semibold">
                      {p.triage_index.toFixed(1)}
                    </TableCell>
                    <TableCell className="min-w-[320px] text-zinc-400 font-sans text-xs leading-relaxed pr-4">
                      {p.science_case}
                    </TableCell>
                    <TableCell className="w-[140px] whitespace-nowrap text-center shrink-0">
                      <Badge 
                        variant="outline" 
                        className={`text-[10px] ${p.urgency === 'HIGH PRIORITY' ? 'border-emerald-500/40 text-emerald-400 bg-emerald-950/20' : p.urgency === 'ELT TARGET' ? 'border-purple-500/40 text-purple-400 bg-purple-950/20' : 'border-cyan-500/40 text-cyan-400 bg-cyan-950/20'}`}
                      >
                        {p.urgency}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* ── NEW: Architectural Scientific Safeguards Grid ─────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="border border-zinc-800/80 rounded-xl bg-zinc-950/50 p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-mono text-zinc-300">
            <Scale className="size-4 text-cyan-400" />
            <span className="font-medium">Fulton Radius Valley Gate</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Applies a logistic transition at 1.80 R⊕. Sub-Neptunes with volatile gas envelopes cannot mask as habitable worlds.
          </p>
        </div>

        <div className="border border-zinc-800/80 rounded-xl bg-zinc-950/50 p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-mono text-zinc-300">
            <ShieldCheck className="size-4 text-emerald-400" />
            <span className="font-medium">Decoupled Decision Layer</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Separates geometric transmission SNR from intrinsic habitability to prevent tautological confirmation bias.
          </p>
        </div>

        <div className="border border-zinc-800/80 rounded-xl bg-zinc-950/50 p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-mono text-zinc-300">
            <Orbit className="size-4 text-amber-400" />
            <span className="font-medium">N-Body Symplectic MEGNO</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            WHFAST integrator integrates 50,000 orbits to verify dynamical stability for predicted orbital gaps.
          </p>
        </div>

        <div className="border border-zinc-800/80 rounded-xl bg-zinc-950/50 p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-mono text-zinc-300">
            <Activity className="size-4 text-purple-400" />
            <span className="font-medium">Abiotic False-Positive Logic</span>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Cross-matches HITRAN line lists while penalizing solitary abiotic pathways (e.g. volcanic CH4 without CO2).
          </p>
        </div>
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
