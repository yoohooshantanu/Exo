import { useParams, Link } from 'react-router-dom'
import { usePlanet, useSpectrum, useRetrievals } from '@/hooks/useApi'
import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
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
import { Button } from '@/components/ui/button'
import { ArrowLeft, AlertTriangle, Play, CheckCircle2, Loader2, XCircle, Telescope } from 'lucide-react'
import { PosteriorPlots } from '@/components/PosteriorPlots'
import { ErrorCard } from '@/components/ErrorCard'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
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
  const { data: planet, isLoading, isError: pError, refetch: refetchPlanet } = usePlanet(name ?? '')
  const { data: spectrum, isLoading: isSpectrumLoading, isError: sError, refetch: refetchSpectrum } = useSpectrum(name ?? '')
  const specId = spectrum?.spec_id ?? ''
  
  const queryClient = useQueryClient()
  const { data: retrievals } = useRetrievals(name ?? '', specId)
  
  const retrieveMutation = useMutation({
    mutationFn: () => api.startRetrieval(name ?? '', specId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['retrievals', name, specId] })
    }
  })

  const radarData = useMemo(() => {
    if (!planet) return []
    // Retain all 7 axes; plot genuine zero or missing as 0 while distinguishing missing in raw
    const toPercent = (v?: number | null) => (v != null && v >= 0 ? Number((v * 100).toFixed(1)) : 0)
    return [
      { axis: 'Radius', value: toPercent(planet.habitability.radius_esi_score), isMissing: planet.habitability.radius_esi_score == null },
      { axis: 'Mass', value: toPercent(planet.habitability.mass_esi_score), isMissing: planet.habitability.mass_esi_score == null },
      { axis: 'Temp', value: toPercent(planet.habitability.teq_score), isMissing: planet.habitability.teq_score == null },
      { axis: 'HZ', value: toPercent(planet.habitability.hz_score), isMissing: planet.habitability.hz_score == null },
      { axis: 'Tidal', value: toPercent(planet.anomaly_risk.tidal_lock_score), isMissing: planet.anomaly_risk.tidal_lock_score == null },
      { axis: 'Escape', value: toPercent(planet.anomaly_risk.xuv_escape_score), isMissing: planet.anomaly_risk.xuv_escape_score == null },
      { axis: 'Ecc', value: toPercent(planet.habitability.eccentricity_score), isMissing: planet.habitability.eccentricity_score == null },
    ]
  }, [planet])

  const riskData = useMemo(() => {
    if (!planet) return []
    return [
      { name: 'XUV Escape', score: planet.anomaly_risk.xuv_escape_score ?? 0 },
      { name: 'Tidal', score: planet.anomaly_risk.tidal_lock_score ?? 0 },
      { name: 'Ecc', score: planet.habitability.eccentricity_score ?? 0 },
      { name: 'Age', score: planet.habitability.age_score ?? 0 },
    ]
  }, [planet])

  const spectrumData = useMemo(() => {
    if (!spectrum?.points?.length) return []
    return spectrum.points
      .filter(p => p.depth_ppm != null)
      .map(p => ({ wavelength: p.wavelength_um, depth: p.depth_ppm }))
      .sort((a, b) => a.wavelength - b.wavelength)
  }, [spectrum])

  const completedRetrievalId = retrievals?.find(r => r.status === 'completed')?.id

  if (pError) {
    return (
      <div className="p-6 h-[50vh]">
        <ErrorCard 
          message="Failed to load planet details." 
          onRetry={() => { refetchPlanet(); }} 
        />
      </div>
    )
  }

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

  const comp = planet.habitability.composite_score ?? 0
  const uniqueMols = [...new Set(planet.biosignatures.molecules)]

  const systemArchitectureItems = [
    ...(planet.system_planets || []).map(p => ({
      type: 'planet' as const,
      name: p.planet_name,
      period: p.period_days || 0,
      mass: p.mass_earth,
      radius: p.radius_earth,
      isTarget: p.planet_name === planet.planet_name
    })),
    ...(planet.orbital_gaps || []).map(g => ({
      type: 'gap' as const,
      name: 'Predicted Gap',
      period: g.predicted_period_days,
      mass: g.mass_min_earth && g.mass_max_earth ? (g.mass_min_earth + g.mass_max_earth) / 2 : undefined,
      mass_min: g.mass_min_earth,
      mass_max: g.mass_max_earth,
      confidence: g.stability_confidence,
      hint: g.detection_method_hint,
      isTarget: false
    }))
  ].sort((a, b) => a.period - b.period)

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
                {planet.anomaly_risk.anomaly_types.length > 0 && (
                  <Badge variant="destructive" className="text-xs">
                    {planet.anomaly_risk.anomaly_count} ANOMAL{planet.anomaly_risk.anomaly_count === 1 ? 'Y' : 'IES'}
                  </Badge>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-3 text-right shrink-0">
              <div className="flex gap-6 items-end justify-end border-b border-border pb-3">
                <div>
                  <div className="text-2xl font-light text-chart-1">
                    {planet.observability_index != null
                      ? planet.observability_index.toFixed(1)
                      : '—'}
                  </div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground mt-1" title="Geometric SNR / TSM-style proxy">Observability</p>
                </div>
                <div>
                  <div className="text-2xl font-light text-chart-2">
                    {planet.physical_triage_index != null
                      ? planet.physical_triage_index.toFixed(1)
                      : '—'}
                  </div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground mt-1" title="Habitability − Anomaly Penalty">Physical Triage</p>
                </div>
                <div>
                  <div className="text-2xl font-light text-chart-3">
                    {planet.characterization_index != null
                      ? planet.characterization_index.toFixed(1)
                      : '—'}
                  </div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground mt-1" title="Biosignatures + Data Quality (Post-observation enrichment)">Characterization</p>
                </div>
              </div>
              
              <div className="flex justify-end gap-2 items-center mt-1">
                <p className="text-[11px] text-muted-foreground">
                  Composite: <span className="font-mono">
                    {planet.habitability?.composite_score?.toFixed(2) ?? '—'} 
                    {planet.habitability?.composite_score_iqr ? ` ± ${planet.habitability.composite_score_iqr.toFixed(2)}` : ''}
                  </span>
                </p>
                {planet.habitability?.is_imputed && (
                  <Badge variant="outline" className="text-[9px] border-amber-500/50 text-amber-500 hover:bg-amber-500/10" title="Mass imputed from radius ($M \sim R^3$). XUV score and composite IQR unreliable.">
                    Mass Imputed
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Key Scores — simple stat cards matching reference ─────── */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { val: planet.habitability?.similarity_score ?? 0, label: 'Similarity', desc: 'Earth Similarity Index' },
          { val: planet.anomaly_risk?.safety_score ?? 0, label: 'Safety', desc: 'Environmental safety factor' },
          { val: planet.habitability?.hz_score ?? 0, label: 'HZ Position', desc: 'Habitable zone proximity' },
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
                  { prop: 'Radius', val: planet.radius_earth, earth: '1.00', unit: 'R⊕', key: 'radius_earth' as const },
                  { prop: 'Mass', val: planet.mass_earth, earth: '1.00', unit: 'M⊕', key: 'mass_earth' as const },
                  { prop: 'Period', val: planet.period_days, earth: '365.25', unit: 'd', key: 'period_days' as const },
                  { prop: 'Semi-major axis', val: planet.semi_major_axis_au, earth: '1.00', unit: 'AU', key: 'semi_major_axis_au' as const },
                  { prop: 'Temperature', val: planet.eq_temperature_k, earth: '255', unit: 'K', key: 'eq_temperature_k' as const },
                  { prop: 'Eccentricity', val: planet.eccentricity, earth: '0.017', unit: '', key: 'eccentricity' as const },
                ].map(row => (
                  <TableRow key={row.prop}>
                    <TableCell className="text-muted-foreground">
                      {row.prop}
                      <ProvenanceBadge
                        provenance={planet.data_provenance?.[row.key]}
                        className="ml-1.5 align-middle"
                      />
                    </TableCell>
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
                <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="75%">
                  <PolarGrid stroke="hsl(var(--muted-foreground)/0.2)" />
                  <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
                  <PolarRadiusAxis 
                    domain={[0, 100]} 
                    angle={90} 
                    tickCount={6} 
                    tickFormatter={(v) => (Number(v) / 100).toFixed(1)}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground)/0.7)' }} 
                    stroke="hsl(var(--muted-foreground)/0.2)" 
                  />
                  <ChartTooltip 
                    content={
                      <ChartTooltipContent 
                        formatter={(value, _name, item: any) => item?.payload?.isMissing ? "Unmeasured" : `${(Number(value) / 100).toFixed(3)} (${value}%)`} 
                      />
                    } 
                  />
                  <Radar dataKey="value" fill="var(--chart-1)" fillOpacity={0.25} stroke="var(--chart-1)" strokeWidth={1.5} dot={{ r: 2.5, fill: 'var(--chart-1)' }} />
                </RadarChart>
              </ChartContainer>
            ) : (
              <p className="text-sm text-muted-foreground py-12 text-center">Insufficient data</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── System Architecture & Orbital Gaps ──────────────────── */}
      {systemArchitectureItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">System Architecture</CardTitle>
            <CardDescription>Known planets and predicted gaps sorted by orbital period</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              {systemArchitectureItems.map((item, idx) => (
                <div 
                  key={idx} 
                  className={`flex items-center justify-between p-3 rounded-md ${
                    item.type === 'gap' 
                      ? 'bg-destructive/10' 
                      : item.isTarget
                        ? 'bg-primary/10'
                        : 'bg-card'
                  }`}
                >
                  <div className="flex items-center gap-4">
                    <div className="w-8 text-center text-xs text-muted-foreground font-data">
                      {idx + 1}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`font-medium ${item.type === 'gap' ? 'text-destructive' : ''}`}>
                          {item.name}
                        </span>
                        {item.type === 'gap' && (
                          <Badge variant="destructive" className="text-[10px] h-5">PREDICTED</Badge>
                        )}
                        {item.isTarget && (
                          <Badge variant="default" className="text-[10px] h-5">CURRENT</Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1 font-data">
                        Period: {item.period.toFixed(2)} days
                      </div>
                    </div>
                  </div>
                  
                  <div className="text-right">
                    {item.type === 'gap' ? (
                      <>
                        <div className="text-sm font-data">
                          {item.mass_min?.toFixed(1)} - {item.mass_max?.toFixed(1)} M<sub className="text-[10px]">⊕</sub>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Confidence: {(item.confidence! * 100).toFixed(1)}% · {item.hint}
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="text-sm font-data">
                          {item.mass ? `${item.mass.toFixed(2)} M⊕` : 'Mass Unknown'}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Radius: {item.radius ? `${item.radius.toFixed(2)} R⊕` : 'Unknown'}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

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

      {/* ── Spectrum & Explainability Layer ────────────────────────── */}
      {isSpectrumLoading ? (
        <Card className="border border-zinc-800/80 bg-zinc-950/60">
          <CardHeader>
            <CardTitle className="text-sm font-medium">Atmospheric Transmission Spectrum</CardTitle>
            <CardDescription>Loading spectroscopic data...</CardDescription>
          </CardHeader>
          <CardContent className="h-48 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </CardContent>
        </Card>
      ) : sError ? (
        <div className="h-48">
          <ErrorCard
            message="Unable to load spectrum data."
            onRetry={() => { refetchSpectrum(); }}
          />
        </div>
      ) : !spectrum ? (
        <Card className="border border-zinc-800/80 bg-zinc-950/60">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-white flex items-center gap-2">
              <Telescope className="size-4 text-zinc-400" />
              <span>Atmospheric Transmission Spectrum</span>
            </CardTitle>
            <CardDescription className="text-xs text-zinc-400">
              Spectroscopic observation archive status
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-lg border border-zinc-800/60 bg-zinc-900/40 p-4 text-xs text-zinc-400 space-y-1.5">
              <p className="text-zinc-200 font-medium font-mono">
                No Transmission Spectrum Ingested Yet
              </p>
              <p className="leading-relaxed">
                No transmission spectrum is currently ingested in the Exo database for this target.
                {planet.observability_index != null ? (
                  <> Geometric Observability Index: <strong className="text-zinc-300 font-mono">{planet.observability_index.toFixed(1)}</strong>.</>
                ) : (
                  <> Observability Index: <span className="font-mono text-zinc-400">N/A</span>.</>
                )}
              </p>
            </div>
          </CardContent>
        </Card>
      ) : spectrumData.length === 0 ? (
        <Card className="border border-zinc-800/80 bg-zinc-950/60">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-white flex items-center gap-2">
              <Telescope className="size-4 text-zinc-400" />
              <span>Atmospheric Transmission Spectrum</span>
            </CardTitle>
            <CardDescription className="text-xs text-zinc-400">
              {spectrum.instrument || 'Unknown instrument'} / {spectrum.facility || 'Unknown facility'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-lg border border-zinc-800/60 bg-zinc-900/40 p-4 text-xs text-zinc-400 space-y-1.5">
              <p className="text-zinc-200 font-medium font-mono">
                No Spectral Points Available
              </p>
              <p className="leading-relaxed">
                Spectrum record available ({spectrum.spec_id}), but no plottable spectral measurements were returned.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-sm font-medium">Detection Explainability Layer</CardTitle>
              <CardDescription>
                {spectrum?.instrument} / {spectrum?.facility}
              </CardDescription>
            </div>
            
            <div className="flex items-center gap-4">
              {retrievals && retrievals.length > 0 && (
                <div className="text-xs text-muted-foreground flex items-center gap-2">
                  {retrievals[0].status === 'running' && <><Loader2 className="w-3 h-3 animate-spin" /> Retrieving... (can take 2-5 mins)</>}
                  {retrievals[0].status === 'completed' && <><CheckCircle2 className="w-3 h-3 text-green-500" /> PLATON Retrieval Completed</>}
                  {retrievals[0].status === 'failed' && <><XCircle className="w-3 h-3 text-destructive" /> PLATON Retrieval Failed</>}
                </div>
              )}
              <Button 
                variant="secondary" 
                size="sm" 
                className="h-8 gap-2"
                onClick={() => retrieveMutation.mutate()}
                disabled={retrieveMutation.isPending || retrievals?.some(r => r.status === 'running')}
              >
                {retrieveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Run Full Retrieval
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {spectrum?.detections && spectrum.detections.length > 0 && (
              <div className="mb-6 grid gap-4 grid-cols-1 md:grid-cols-3">
                {[...new Map(spectrum.detections.map(d => [d.molecule, d])).values()].map((d, i) => (
                  <div key={i} className="p-3 border rounded-md bg-secondary/20 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="font-data text-foreground font-medium text-sm">{d.molecule.toUpperCase()}</span>
                      <Badge variant={d.detection_sigma >= 3 ? "destructive" : "secondary"}>
                        {d.detection_sigma.toFixed(2)}σ
                      </Badge>
                    </div>
                    {/* Method Notes & Contamination Penalties */}
                    <div className="text-xs text-muted-foreground break-words whitespace-pre-wrap">
                      {d.method_notes ? d.method_notes : "No penalties applied. Feature clearly isolated."}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-2 border-t pt-2 flex justify-between">
                      <span>Template peaks: {d.hitran_match_count ?? 0}</span>
                      <span>
                        Abiotic assessment: {d.abiotic_ruled_out === true ? "Ruled out" : d.abiotic_ruled_out === false ? "Not ruled out" : "Not assessed"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <ChartContainer config={spectrumConfig} className="max-h-[300px]">
              <AreaChart data={spectrumData} margin={{ top: 5, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid opacity={0.3} />
                <XAxis dataKey="wavelength" type="number" domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 10 }}
                  label={{ value: 'Wavelength (μm)', position: 'bottom', fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }}
                  label={{ value: 'Depth (ppm)', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Area dataKey="depth" fill="var(--chart-1)" fillOpacity={0.05} stroke="var(--chart-1)" strokeWidth={1.5} dot={false} />
                
                {/* Template Overlap Visualization */}
                {spectrum?.hitran_lines?.slice(0, 30).map((h, i) => (
                  <ReferenceLine 
                    key={i} 
                    x={h.wavelength_um} 
                    stroke="var(--destructive)" 
                    strokeDasharray="3 3" 
                    strokeOpacity={0.4} 
                  />
                ))}
              </AreaChart>
            </ChartContainer>
            
            <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <span className="w-4 border-t border-destructive border-dashed"></span>
              <span>Molecular Reference-Template Markers (HITRAN Cross-Sections)</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Bayesian Posterior Plots (from PLATON) ───────────────────── */}
      {retrievals && retrievals.length > 0 && retrievals[0].status === 'completed' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Nested Sampling Posterior Distributions</CardTitle>
            <CardDescription>
              Bayesian retrieval via PLATON engine. Displays marginalized 1D probabilities for atmospheric parameters.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PosteriorPlots retrievalId={retrievals[0].retrieval_id} />
          </CardContent>
        </Card>
      )}

      {/* ── Anomalies ──────────────────────────────────────────────── */}
      {planet.anomaly_risk.anomaly_types.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Anomaly Flags</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableBody>
                {planet.anomaly_risk.anomaly_types.map((t, i) => (
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
