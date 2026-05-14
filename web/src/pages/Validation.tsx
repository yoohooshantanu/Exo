import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  RadarChart, PolarGrid, PolarAngleAxis, Radar,
  PieChart, Pie, Cell,
  ScatterChart, Scatter, ZAxis
} from 'recharts'
import {
  ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent
} from '@/components/ui/chart'
import { ShieldCheck, Activity, Target, Orbit, FlaskConical, AlertTriangle, Cpu, Telescope } from 'lucide-react'
import type { ChartConfig } from '@/components/ui/chart'
import { api } from '@/lib/api'

const MOL_LABELS: Record<string, string> = {
  h2o: 'H₂O', co2: 'CO₂', o3: 'O₃', ch4: 'CH₄',
  co: 'CO', nh3: 'NH₃', so2: 'SO₂',
}

const CHART_COLORS = [
  'var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)',
  'var(--chart-4)', 'var(--chart-5)',
  'hsl(200, 70%, 50%)', 'hsl(340, 70%, 50%)',
]

// Chart configs
const molBarConfig = {
  confirmed: { label: 'Confirmed (≥3σ)', color: 'var(--chart-1)' },
  marginal: { label: 'Marginal (2-3σ)', color: 'var(--chart-3)' },
} satisfies ChartConfig

const orbResonanceConfig = {
  count: { label: 'Predictions', color: 'var(--chart-2)' },
} satisfies ChartConfig

const orbConfConfig = {
  value: { label: 'Count', color: 'var(--chart-1)' },
} satisfies ChartConfig

const habHistConfig = {
  count: { label: 'Planets', color: 'var(--chart-1)' },
} satisfies ChartConfig

const anomConfig = {
  count: { label: 'Flags', color: 'var(--destructive)' },
} satisfies ChartConfig

const radarConfig = {
  value: { label: 'Metric', color: 'var(--chart-1)' },
} satisfies ChartConfig


export default function Validation() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.validationMetrics().then(d => { setData(d); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto space-y-6 pb-12">
        <Skeleton className="h-12 w-96" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
        <div className="grid grid-cols-2 gap-6">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-80" />)}
        </div>
      </div>
    )
  }

  if (!data) return <p className="text-center text-muted-foreground py-24">Failed to load metrics.</p>

  const bio = data.biosignatures
  const orb = data.orbital
  const hab = data.habitability
  const anom = data.anomalies
  const ret = data.retrievals

  // Prepare data for charts
  const molChartData = bio.by_molecule.map((m: any) => ({
    molecule: MOL_LABELS[m.molecule] || m.molecule,
    confirmed: m.confirmed,
    marginal: m.marginal,
    avgSigma: m.avg_sigma,
  }))

  const resonanceLabel = (s: string) => {
    const match = s.match(/\((.+)\)/)
    return match ? match[1] : s
  }

  const orbResonanceData = orb.by_resonance.map((r: any) => ({
    resonance: resonanceLabel(r.resonance),
    count: r.count,
  }))

  const orbConfData = [
    { name: 'High (≥90%)', value: orb.high_confidence, fill: 'var(--chart-1)' },
    { name: 'Mid (80-90%)', value: orb.mid_confidence, fill: 'var(--chart-3)' },
    { name: 'Low (<80%)', value: orb.low_confidence, fill: 'var(--chart-4)' },
  ]

  const habHistData = hab.histogram.map((h: any) => ({
    bin: h.bin,
    count: h.count,
  }))

  const anomChartData = anom.by_type.map((a: any) => ({
    type: a.type.replace(/_/g, ' '),
    count: a.count,
    avgSigma: a.avg_sigma,
  }))

  // Module health radar
  const moduleRadarData = [
    { metric: 'Biosig Detections', value: Math.min(bio.total_detections / 10, 100) },
    { metric: 'Orbital Gaps', value: Math.min(orb.total_predictions / 15, 100) },
    { metric: 'Habitability Scored', value: Math.min(hab.total_scored / 500, 100) },
    { metric: 'Anomaly Coverage', value: Math.min(anom.total_flags / 10, 100) },
    { metric: 'Retrievals', value: Math.min(ret.total * 15, 100) },
  ]

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-3xl font-light tracking-tight flex items-center gap-3">
            <ShieldCheck className="w-8 h-8 text-chart-1" />
            Platform Validation
          </h1>
          <p className="text-muted-foreground mt-2">
            Real-time benchmarks and diagnostics across all scientific engines
          </p>
        </div>
        <div className="text-right">
          <p className="font-data text-2xl text-foreground">{bio.total_detections + orb.total_predictions + hab.total_scored}</p>
          <p className="text-xs uppercase tracking-widest text-muted-foreground mt-1">Total Computations</p>
        </div>
      </div>

      {/* ── Top-Level Stats ────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { icon: FlaskConical, label: 'Biosig Detections', val: bio.total_detections.toLocaleString(), sub: `${bio.total_confirmed} confirmed (≥3σ)` },
          { icon: Orbit, label: 'Orbital Predictions', val: orb.total_predictions.toLocaleString(), sub: `${orb.avg_confidence.toFixed(1)}% avg confidence` },
          { icon: Target, label: 'Habitability Scored', val: hab.total_scored.toLocaleString(), sub: `${hab.tier1_count} in Tier 1 (≥0.7)` },
          { icon: AlertTriangle, label: 'Anomaly Flags', val: anom.total_flags.toLocaleString(), sub: `${anom.by_type.length} categories` },
        ].map((stat, i) => (
          <Card key={i}>
            <CardContent className="p-4 flex items-center gap-4">
              <div className="p-3 bg-secondary rounded-lg shrink-0">
                <stat.icon className="w-5 h-5 text-chart-1" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
                <p className="font-data text-xl mt-0.5">{stat.val}</p>
                <p className="text-[11px] text-muted-foreground truncate">{stat.sub}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── BIOSIGNATURE DETECTION ────────────────────────────── */}
      <div className="space-y-2">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <FlaskConical className="w-5 h-5 text-chart-1" /> Biosignature Detection Engine
          <Badge variant="secondary" className="text-[10px] ml-2">v3.0.0</Badge>
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Molecule Detection Breakdown */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Detection Breakdown by Molecule</CardTitle>
            <CardDescription>Confirmed (≥3σ) vs Marginal (2-3σ) detections</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            <ChartContainer config={molBarConfig} className="h-[300px] w-full">
              <BarChart data={molChartData} margin={{ top: 5, right: 20, bottom: 20, left: 0 }}>
                <CartesianGrid vertical={false} opacity={0.3} />
                <XAxis dataKey="molecule" tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="confirmed" stackId="a" fill="var(--chart-1)" radius={[0, 0, 0, 0]} />
                <Bar dataKey="marginal" stackId="a" fill="var(--chart-3)" radius={[4, 4, 0, 0]} />
                <ChartLegend content={<ChartLegendContent />} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        {/* Molecule Sigma Table */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Per-Molecule Performance</CardTitle>
            <CardDescription>Average detection sigma and confirmation rate</CardDescription>
          </CardHeader>
          <CardContent className="flex-1">
            <div className="space-y-3">
              {bio.by_molecule.map((m: any) => {
                const confRate = m.total > 0 ? ((m.confirmed / m.total) * 100).toFixed(1) : '0.0'
                return (
                  <div key={m.molecule} className="flex items-center justify-between p-3 rounded-md bg-secondary/30">
                    <div className="flex items-center gap-3">
                      <span className="font-medium text-sm w-12">{MOL_LABELS[m.molecule] || m.molecule}</span>
                      <Badge variant="outline" className="text-[10px]">{m.total} total</Badge>
                    </div>
                    <div className="text-right">
                      <span className="font-data text-sm">σ̄ = {m.avg_sigma}</span>
                      <span className="text-xs text-muted-foreground ml-3">Confirm: {confRate}%</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── ORBITAL GAP PREDICTOR ──────────────────────────────── */}
      <div className="space-y-2 pt-4">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Orbit className="w-5 h-5 text-chart-2" /> Orbital Gap Predictor
          <Badge variant="secondary" className="text-[10px] ml-2">v3.1.0</Badge>
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Resonance Distribution */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Predictions by Resonance Type</CardTitle>
            <CardDescription>Mean-motion resonance distribution across {orb.total_predictions} gap candidates</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            <ChartContainer config={orbResonanceConfig} className="h-[300px] w-full">
              <BarChart data={orbResonanceData} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid horizontal={false} opacity={0.3} />
                <XAxis type="number" tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <YAxis dataKey="resonance" type="category" tickLine={false} axisLine={false} width={120} tick={{ fontSize: 11 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="count" fill="var(--chart-2)" radius={[0, 4, 4, 0]} maxBarSize={30} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        {/* Stability Confidence Distribution */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Stability Confidence Distribution</CardTitle>
            <CardDescription>MEGNO-verified N-body stability tiers (avg {orb.avg_nbody_runs?.toLocaleString()} orbits/run)</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            <ChartContainer config={orbConfConfig} className="mx-auto aspect-square max-h-[280px]">
              <PieChart>
                <Pie data={orbConfData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                     innerRadius={60} outerRadius={100} strokeWidth={2} stroke="var(--background)">
                  {orbConfData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <ChartTooltip content={<ChartTooltipContent />} />
                <ChartLegend content={<ChartLegendContent />} />
              </PieChart>
            </ChartContainer>
          </CardContent>
        </Card>
      </div>

      {/* ── HABITABILITY SCORING ───────────────────────────────── */}
      <div className="space-y-2 pt-4">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Target className="w-5 h-5 text-chart-3" /> Habitability Scorer
          <Badge variant="secondary" className="text-[10px] ml-2">v4.2.0</Badge>
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Score Distribution Histogram */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Composite Score Distribution</CardTitle>
            <CardDescription>ESI-based habitability across {hab.total_scored.toLocaleString()} planets</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            <ChartContainer config={habHistConfig} className="h-[300px] w-full">
              <BarChart data={habHistData} margin={{ top: 5, right: 20, bottom: 20, left: 0 }}>
                <CartesianGrid vertical={false} opacity={0.3} />
                <XAxis dataKey="bin" tickLine={false} axisLine={false} tick={{ fontSize: 10 }}
                  label={{ value: 'Score Range', position: 'bottom', offset: 0, fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12 }}
                  label={{ value: 'Planet Count', angle: -90, position: 'insideLeft', offset: 15, fontSize: 11 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="count" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        {/* Habitability Tier Breakdown */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Tier Classification</CardTitle>
            <CardDescription>Score range: {hab.min_score} — {hab.max_score} (mean: {hab.avg_score.toFixed(3)})</CardDescription>
          </CardHeader>
          <CardContent className="flex-1">
            <div className="space-y-6 pt-4">
              {[
                { label: 'Tier 1 — High Priority', desc: 'Composite ≥ 0.70', count: hab.tier1_count, color: 'bg-chart-1' },
                { label: 'Tier 2 — Moderate', desc: 'Composite 0.40 – 0.69', count: hab.tier2_count, color: 'bg-chart-3' },
                { label: 'Tier 3 — Low / Hostile', desc: 'Composite < 0.40', count: hab.tier3_count, color: 'bg-chart-4' },
              ].map((tier, i) => {
                const pct = hab.total_scored > 0 ? (tier.count / hab.total_scored * 100).toFixed(1) : 0
                return (
                  <div key={i}>
                    <div className="flex justify-between items-center mb-2">
                      <div>
                        <p className="text-sm font-medium">{tier.label}</p>
                        <p className="text-xs text-muted-foreground">{tier.desc}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-data text-lg">{tier.count.toLocaleString()}</p>
                        <p className="text-[11px] text-muted-foreground">{pct}%</p>
                      </div>
                    </div>
                    <div className="h-2 bg-secondary rounded-full overflow-hidden">
                      <div className={`h-full ${tier.color} rounded-full transition-all`}
                        style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── ANOMALY DETECTION & RETRIEVALS ──────────────────────── */}
      <div className="space-y-2 pt-4">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-destructive" /> Anomaly Detection & Bayesian Retrievals
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Anomaly Flags by Type */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Anomaly Flag Distribution</CardTitle>
            <CardDescription>{anom.total_flags} total flags across {anom.by_type.length} categories</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            <ChartContainer config={anomConfig} className="h-[300px] w-full">
              <BarChart data={anomChartData} margin={{ top: 5, right: 20, bottom: 40, left: 0 }}>
                <CartesianGrid vertical={false} opacity={0.3} />
                <XAxis dataKey="type" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} angle={-15} textAnchor="end" />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="count" fill="var(--destructive)" radius={[4, 4, 0, 0]} maxBarSize={50} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        {/* PLATON Retrieval Status + Module Health Radar */}
        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Module Health Overview</CardTitle>
            <CardDescription>Cross-engine coverage and PLATON retrieval status</CardDescription>
          </CardHeader>
          <CardContent className="flex-1">
            {/* Retrieval status row */}
            <div className="grid grid-cols-3 gap-3 mb-6">
              {[
                { label: 'Completed', val: ret.completed, color: 'text-chart-1' },
                { label: 'Running', val: ret.running, color: 'text-chart-3' },
                { label: 'Failed', val: ret.failed, color: 'text-destructive' },
              ].map((s, i) => (
                <div key={i} className="text-center p-3 bg-secondary/30 rounded-md">
                  <p className={`font-data text-2xl ${s.color}`}>{s.val}</p>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">{s.label}</p>
                </div>
              ))}
            </div>

            {/* Module Radar */}
            <ChartContainer config={radarConfig} className="mx-auto aspect-square max-h-[200px]">
              <RadarChart data={moduleRadarData} cx="50%" cy="50%" outerRadius="70%">
                <PolarGrid opacity={0.3} />
                <PolarAngleAxis dataKey="metric" tick={{ fontSize: 9 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Radar dataKey="value" fill="var(--chart-1)" fillOpacity={0.15} stroke="var(--chart-1)" strokeWidth={1.5} />
              </RadarChart>
            </ChartContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
