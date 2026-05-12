import { useParams, Link } from 'react-router-dom'
import { usePlanet, useSpectrum } from '@/hooks/useApi'
import { useMemo } from 'react'
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis,
  AreaChart, Area, XAxis, YAxis,
  ReferenceLine, CartesianGrid,
  BarChart, Bar
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  ChartContainer, ChartTooltip, ChartTooltipContent
} from '@/components/ui/chart'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import AnimatedNumber from '@/components/AnimatedNumber'
import { ArrowLeft, AlertTriangle } from 'lucide-react'
import type { ChartConfig } from '@/components/ui/chart'

const radarConfig = {
  value: { label: 'Score', color: 'var(--chart-1)' },
} satisfies ChartConfig

const spectrumConfig = {
  depth: { label: 'Depth (ppm)', color: 'var(--chart-1)' },
} satisfies ChartConfig

const barConfig = {
  score: { label: 'Score', color: 'var(--chart-1)' },
} satisfies ChartConfig

function tierLabel(s: number): string {
  if (s >= 0.8) return 'EXCEPTIONAL'
  if (s >= 0.7) return 'HIGH PRIORITY'
  if (s >= 0.6) return 'MODERATE'
  if (s >= 0.4) return 'LOW'
  return 'MARGINAL'
}

export default function PlanetDetail() {
  const { name } = useParams<{ name: string }>()
  const { data: planet, isLoading } = usePlanet(name ?? '')
  const { data: spectrum } = useSpectrum(name ?? '')

  const radarData = useMemo(() => {
    if (!planet) return []
    return [
      { axis: 'Radius', value: planet.radius_esi_score ?? 0 },
      { axis: 'Mass', value: planet.mass_esi_score ?? 0 },
      { axis: 'Temp', value: planet.teq_score ?? 0 },
      { axis: 'HZ', value: planet.hz_score ?? 0 },
      { axis: 'Tidal', value: planet.tidal_lock_score ?? 0 },
      { axis: 'Flare', value: planet.flare_score ?? 0 },
      { axis: 'Ecc', value: planet.eccentricity_score ?? 0 },
    ].filter(d => d.value > 0)
  }, [planet])

  const riskData = useMemo(() => {
    if (!planet) return []
    return [
      { name: 'Flares', score: planet.flare_score ?? 0 },
      { name: 'Tidal', score: planet.tidal_lock_score ?? 0 },
      { name: 'Ecc', score: planet.eccentricity_score ?? 0 },
      { name: 'Age', score: planet.age_score ?? 0 },
    ]
  }, [planet])

  const spectrumData = useMemo(() => {
    if (!spectrum?.points?.length) return []
    return spectrum.points
      .filter(p => p.depth_ppm != null)
      .map(p => ({ wavelength: p.wavelength_um, depth: p.depth_ppm }))
      .sort((a, b) => a.wavelength - b.wavelength)
  }, [spectrum])

  if (isLoading || !planet) {
    return (
      <div className="space-y-6 max-w-5xl mx-auto">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-32 w-full" />
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" />
        </div>
      </div>
    )
  }

  const comp = planet.composite_score ?? 0
  const uniqueMols = [...new Set(planet.molecules)]

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Link to="/planets" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
        <ArrowLeft className="w-4 h-4" /> Catalog
      </Link>

      {/* ── Hero ───────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="p-6">
          <div className="flex justify-between items-start">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Badge variant="secondary">{tierLabel(comp)}</Badge>
                {planet.cluster_name && (
                  <Badge variant="outline" className="text-muted-foreground">{planet.cluster_name}</Badge>
                )}
              </div>
              <h1 className="text-3xl font-light tracking-tight">{planet.planet_name}</h1>
              <p className="text-sm text-muted-foreground mt-1">
                {planet.hostname} · {planet.discovery_method} · {planet.discovery_year}
              </p>
              <div className="flex gap-2 mt-4 flex-wrap">
                {uniqueMols.map(m => (
                  <Badge key={m} variant="secondary" className="font-data text-xs">{m}</Badge>
                ))}
                {planet.anomaly_types.length > 0 && (
                  <Badge variant="destructive" className="text-xs">
                    {planet.anomaly_count} ANOMAL{planet.anomaly_count === 1 ? 'Y' : 'IES'}
                  </Badge>
                )}
              </div>
            </div>
            <div className="text-right shrink-0">
              <AnimatedNumber value={comp} decimals={3} className="text-4xl font-light text-chart-1" />
              <p className="text-xs uppercase tracking-widest text-muted-foreground mt-2">Composite</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Key Scores — simple stat cards matching reference ─────── */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { val: planet.similarity_score ?? 0, label: 'Similarity', desc: 'Earth Similarity Index' },
          { val: planet.risk_score ?? 0, label: 'Safety', desc: 'Environmental risk factor' },
          { val: planet.hz_score ?? 0, label: 'HZ Position', desc: 'Habitable zone proximity' },
        ].map((g) => (
          <Card key={g.label}>
            <CardHeader className="pb-2">
              <CardDescription className="text-xs">{g.label}</CardDescription>
              <CardTitle className="text-2xl font-light tracking-tight font-data">
                {g.val.toFixed(3)}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <p className="text-xs text-muted-foreground">{g.desc}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Properties Table + Radar ───────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Physical Properties as a clean table */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Physical Properties</CardTitle>
            <CardDescription>Compared to Earth</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Property</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right">Earth</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  { prop: 'Radius', val: planet.radius_earth, earth: '1.00', unit: 'R⊕' },
                  { prop: 'Mass', val: planet.mass_earth, earth: '1.00', unit: 'M⊕' },
                  { prop: 'Period', val: planet.period_days, earth: '365.25', unit: 'd' },
                  { prop: 'Semi-major axis', val: planet.semi_major_axis_au, earth: '1.00', unit: 'AU' },
                  { prop: 'Temperature', val: planet.eq_temperature_k, earth: '255', unit: 'K' },
                  { prop: 'Eccentricity', val: planet.eccentricity, earth: '0.017', unit: '' },
                ].map(row => (
                  <TableRow key={row.prop}>
                    <TableCell className="text-muted-foreground">{row.prop}</TableCell>
                    <TableCell className="text-right font-data">
                      {row.val != null ? `${Number(row.val).toFixed(2)} ${row.unit}` : '—'}
                    </TableCell>
                    <TableCell className="text-right font-data text-muted-foreground">
                      {row.earth} {row.unit}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Radar Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Score Components</CardTitle>
            <CardDescription>ESI breakdown</CardDescription>
          </CardHeader>
          <CardContent>
            {radarData.length > 0 ? (
              <ChartContainer config={radarConfig} className="mx-auto aspect-square max-h-[280px]">
                <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="70%">
                  <PolarGrid />
                  <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11 }} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Radar dataKey="value" fill="var(--chart-1)" fillOpacity={0.15} stroke="var(--chart-1)" strokeWidth={1.5} />
                </RadarChart>
              </ChartContainer>
            ) : (
              <p className="text-sm text-muted-foreground py-12 text-center">Insufficient data</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Risk Bar Chart — horizontal bars like reference ─────── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Environmental Risk</CardTitle>
          <CardDescription>Score per risk category</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer config={barConfig} className="max-h-[200px]">
            <BarChart data={riskData} layout="vertical" margin={{ left: 0, right: 12 }}>
              <XAxis type="number" domain={[0, 1]} hide />
              <YAxis
                dataKey="name"
                type="category"
                tickLine={false}
                axisLine={false}
                width={60}
                tick={{ fontSize: 12 }}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="score" fill="var(--chart-1)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>

      {/* ── Spectrum ───────────────────────────────────────────────── */}
      {spectrumData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Transmission Spectrum</CardTitle>
            {spectrum && (
              <CardDescription>{spectrum.instrument}</CardDescription>
            )}
          </CardHeader>
          <CardContent>
            <ChartContainer config={spectrumConfig} className="max-h-[240px]">
              <AreaChart data={spectrumData} margin={{ top: 5, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid />
                <XAxis dataKey="wavelength" type="number" domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 10 }}
                  label={{ value: 'Wavelength (μm)', position: 'bottom', fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }}
                  label={{ value: 'Depth (ppm)', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Area dataKey="depth" fill="var(--chart-1)" fillOpacity={0.08} stroke="var(--chart-1)" strokeWidth={1.5} dot={false} />
                {spectrum?.hitran_lines?.slice(0, 15).map((h, i) => (
                  <ReferenceLine key={i} x={h.wavelength_um} stroke="var(--destructive)" strokeDasharray="3 3" strokeOpacity={0.3} />
                ))}
              </AreaChart>
            </ChartContainer>
            {spectrum?.detections && spectrum.detections.length > 0 && (
              <div className="flex gap-3 mt-3 flex-wrap">
                {[...new Map(spectrum.detections.map(d => [d.molecule, d])).values()].map((d, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs">
                    <span className={`w-1.5 h-1.5 rounded-full ${d.detection_sigma >= 3 ? 'bg-destructive' : 'bg-chart-1'}`} />
                    <span className="font-data text-foreground">{d.molecule.toUpperCase()}</span>
                    <span className="text-muted-foreground">{d.detection_sigma.toFixed(1)}σ</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Anomalies ──────────────────────────────────────────────── */}
      {planet.anomaly_types.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Anomaly Flags</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableBody>
                {planet.anomaly_types.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="w-8">
                      <AlertTriangle className="w-4 h-4 text-destructive" />
                    </TableCell>
                    <TableCell>{t}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <div className="text-xs text-muted-foreground font-data pb-8 flex gap-4">
        <span>Model v4.2</span>
        <span>{planet.planet_id?.slice(0, 8)}</span>
        <span>{planet.hostname}</span>
      </div>
    </div>
  )
}
