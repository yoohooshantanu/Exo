import { useMemo } from 'react'
import { usePlanet, useSpectrum } from '@/hooks/useApi'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  ChartContainer, ChartTooltip, ChartTooltipContent
} from '@/components/ui/chart'
import { AlertTriangle, ArrowRight } from 'lucide-react'
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis,
} from 'recharts'
import type { ChartConfig } from '@/components/ui/chart'

const radarConfig = {
  value: { label: 'Score', color: 'var(--chart-1)' },
} satisfies ChartConfig

export default function PlanetDetailPanel({ name }: { name: string }) {
  const { data: planet } = usePlanet(name)
  const { data: spectrum } = useSpectrum(name)

  const esiData = useMemo(() => {
    if (!planet) return []
    return [
      { axis: 'Radius', value: planet.habitability.radius_esi_score ?? 0 },
      { axis: 'Mass', value: planet.habitability.mass_esi_score ?? 0 },
      { axis: 'Temp', value: planet.habitability.teq_score ?? 0 },
      { axis: 'HZ', value: planet.habitability.hz_score ?? 0 },
      { axis: 'Tidal', value: planet.anomaly_risk.tidal_lock_score ?? 0 },
      { axis: 'Flare', value: planet.anomaly_risk.flare_score ?? 0 },
    ].filter(d => d.value > 0)
  }, [planet])

  if (!planet) {
    return <div className="space-y-3 mt-4">
      {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-4 w-full" />)}
    </div>
  }

  return (
    <div className="space-y-5 mt-4">
      <Link to={`/planets/${encodeURIComponent(name)}`}
        className="text-xs text-chart-1 flex items-center gap-1 hover:underline">
        Full dossier <ArrowRight className="w-3 h-3" />
      </Link>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        {[
          ['Radius', planet.radius_earth, 'R⊕'],
          ['Mass', planet.mass_earth, 'M⊕'],
          ['Period', planet.period_days, 'd'],
          ['SMA', planet.semi_major_axis_au, 'AU'],
          ['T_eq', planet.eq_temperature_k, 'K'],
          ['Ecc', planet.eccentricity, ''],
        ].map(([label, val, unit]) => (
          <div key={label as string}>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">{label as string}</p>
            <p className="font-data text-sm text-foreground">
              {val != null ? Number(val).toFixed(3) : '—'}
              {unit && <span className="text-xs text-muted-foreground ml-1">{unit as string}</span>}
            </p>
          </div>
        ))}
      </div>

      <Separator />

      <div>
        <p className="text-xs text-muted-foreground uppercase tracking-wider">Composite</p>
        <p className="font-data text-2xl text-chart-1 mt-1">{planet.habitability.composite_score?.toFixed(4) ?? '—'}</p>
        {planet.cluster_name && (
          <Badge variant="secondary" className="text-xs mt-1">{planet.cluster_name}</Badge>
        )}
      </div>

      {esiData.length > 0 && (
        <>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">ESI Components</p>
            <ChartContainer config={radarConfig} className="mx-auto aspect-square max-h-[180px]">
              <RadarChart data={esiData} cx="50%" cy="50%" outerRadius="75%">
                <PolarGrid />
                <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10 }} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Radar dataKey="value" fill="var(--chart-1)" fillOpacity={0.15} stroke="var(--chart-1)" strokeWidth={1.5} />
              </RadarChart>
            </ChartContainer>
          </div>
        </>
      )}

      {planet.biosignatures.molecules.length > 0 && (
        <>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Detections</p>
            <div className="flex flex-wrap gap-1.5">
              {[...new Set(planet.biosignatures.molecules)].map((m, i) => (
                <Badge key={i} variant="secondary" className="font-data text-xs">{m.toUpperCase()}</Badge>
              ))}
            </div>
          </div>
        </>
      )}

      {spectrum && spectrum.detections.length > 0 && (
        <>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Significance</p>
            <div className="space-y-2">
              {[...new Map(spectrum.detections.map(d => [d.molecule, d])).values()].map((det, i) => (
                <div key={i}>
                  <div className="flex items-center justify-between text-xs mb-0.5">
                    <span className="font-data text-foreground">{det.molecule.toUpperCase()}</span>
                    <span className="font-data text-chart-1">{det.detection_sigma.toFixed(1)}σ</span>
                  </div>
                  <div className="h-1 bg-secondary rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-700" style={{
                      width: `${Math.min(100, det.detection_sigma * 20)}%`,
                      background: det.detection_sigma >= 3 ? 'var(--destructive)' : 'var(--chart-1)',
                    }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {planet.anomaly_risk.anomaly_types.length > 0 && (
        <>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Anomalies</p>
            {planet.anomaly_risk.anomaly_types.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-sm text-muted-foreground py-1">
                <AlertTriangle className="w-3 h-3 text-destructive" /> {t}
              </div>
            ))}
          </div>
        </>
      )}

      <Separator />
      <p className="text-xs text-muted-foreground">{planet.discovery_method} · {planet.discovery_year}</p>
    </div>
  )
}
