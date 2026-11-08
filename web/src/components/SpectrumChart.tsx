import { useMemo, useState } from 'react'
import {
  ComposedChart, Area, Scatter, XAxis, YAxis,
  ReferenceLine, CartesianGrid, ErrorBar, Legend,
  ResponsiveContainer, Tooltip
} from 'recharts'
import type { SpectrumView } from '@/types'

// ── Molecule color palette ──────────────────────────────────────────────────
const MOL_COLORS: Record<string, string> = {
  h2o:  '#3b82f6', // blue
  co2:  '#ef4444', // red
  ch4:  '#22c55e', // green
  o3:   '#a855f7', // purple
  nh3:  '#f97316', // orange
  so2:  '#eab308', // yellow
  co:   '#ec4899', // pink
  hcn:  '#14b8a6', // teal
  no2:  '#f43f5e', // rose
  tio:  '#6366f1', // indigo
}

const getMolColor = (mol: string) =>
  MOL_COLORS[mol.toLowerCase()] ?? '#64748b'

// Chemical formula formatting
const formatMolecule = (mol: string) => {
  const map: Record<string, string> = {
    h2o: 'H₂O', co2: 'CO₂', ch4: 'CH₄', o3: 'O₃',
    nh3: 'NH₃', so2: 'SO₂', co: 'CO', hcn: 'HCN',
    no2: 'NO₂', tio: 'TiO'
  }
  return map[mol.toLowerCase()] ?? mol.toUpperCase()
}

interface SpectrumChartProps {
  spectrum: SpectrumView
}

export function SpectrumChart({ spectrum }: SpectrumChartProps) {
  // ── Molecule toggle state ─────────────────────────────────────────────────
  const allMolecules = useMemo(() => {
    const mols = new Set<string>()
    spectrum.hitran_lines?.forEach(h => mols.add(h.molecule.toLowerCase()))
    spectrum.detections?.forEach(d => mols.add(d.molecule.toLowerCase()))
    return [...mols].sort()
  }, [spectrum])

  const [visibleMols, setVisibleMols] = useState<Set<string>>(
    () => new Set(allMolecules)
  )

  const toggleMol = (mol: string) => {
    setVisibleMols(prev => {
      const next = new Set(prev)
      if (next.has(mol)) next.delete(mol)
      else next.add(mol)
      return next
    })
  }

  // ── Spectrum data points with error bars ───────────────────────────────────
  const chartData = useMemo(() => {
    if (!spectrum?.points?.length) return []
    return spectrum.points
      .filter(p => p.depth_ppm != null)
      .map(p => ({
        wavelength: p.wavelength_um,
        depth: p.depth_ppm!,
        errUp: p.depth_err_upper ?? 0,
        errDown: p.depth_err_lower ?? 0,
        errorY: [Math.abs(p.depth_err_lower ?? 0), Math.abs(p.depth_err_upper ?? 0)],
      }))
      .sort((a, b) => a.wavelength - b.wavelength)
  }, [spectrum])

  // ── HITRAN lines filtered by visible molecules ─────────────────────────────
  const visibleHitran = useMemo(() => {
    if (!spectrum?.hitran_lines) return []
    return spectrum.hitran_lines
      .filter(h => visibleMols.has(h.molecule.toLowerCase()))
  }, [spectrum, visibleMols])

  // ── Detection markers (scatter points at molecule wavelengths) ─────────────
  const detectionMarkers = useMemo(() => {
    if (!spectrum?.detections || !chartData.length) return []
    return spectrum.detections
      .filter(d => visibleMols.has(d.molecule.toLowerCase()))
      .filter(d => d.wavelength_um != null)
      .map(d => {
        // Find the closest spectrum point to this detection wavelength
        const closest = chartData.reduce((prev, curr) =>
          Math.abs(curr.wavelength - (d.wavelength_um ?? 0)) < Math.abs(prev.wavelength - (d.wavelength_um ?? 0))
            ? curr : prev
        )
        return {
          wavelength: d.wavelength_um!,
          depth: closest.depth,
          molecule: d.molecule,
          sigma: d.detection_sigma,
          abiotic: d.abiotic_ruled_out,
          color: getMolColor(d.molecule),
        }
      })
  }, [spectrum, chartData, visibleMols])

  // ── Custom tooltip ─────────────────────────────────────────────────────────
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    if (!d) return null

    return (
      <div className="bg-card/95 backdrop-blur-sm border rounded-lg px-3 py-2 shadow-xl text-xs">
        <div className="font-data text-foreground font-medium">
          λ = {d.wavelength?.toFixed(3)} μm
        </div>
        <div className="text-muted-foreground mt-1">
          Depth: <span className="text-foreground">{d.depth?.toFixed(1)} ppm</span>
        </div>
        {d.errUp > 0 && (
          <div className="text-muted-foreground">
            Error: +{d.errUp?.toFixed(1)} / −{Math.abs(d.errDown)?.toFixed(1)} ppm
          </div>
        )}
        {d.molecule && (
          <div className="mt-1 pt-1 border-t border-border">
            <span style={{ color: getMolColor(d.molecule) }} className="font-medium">
              {formatMolecule(d.molecule)}
            </span>
            {' '}{d.sigma?.toFixed(1)}σ
            {d.abiotic != null && (
              <span className={d.abiotic ? ' text-green-500' : ' text-destructive'}>
                {' '}({d.abiotic ? 'Abiotic ruled out' : 'Abiotic possible'})
              </span>
            )}
          </div>
        )}
      </div>
    )
  }

  if (!chartData.length) return null

  // ── Wavelength domain ─────────────────────────────────────────────────────
  const wMin = Math.floor(chartData[0].wavelength * 10) / 10
  const wMax = Math.ceil(chartData[chartData.length - 1].wavelength * 10) / 10

  return (
    <div className="space-y-4">
      {/* ── Molecule Toggle Pills ──────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2">
        {allMolecules.map(mol => {
          const active = visibleMols.has(mol)
          const detection = spectrum.detections?.find(
            d => d.molecule.toLowerCase() === mol
          )
          return (
            <button
              key={mol}
              onClick={() => toggleMol(mol)}
              className={`
                inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
                transition-all duration-200 border
                ${active
                  ? 'bg-secondary/80 border-border text-foreground shadow-sm'
                  : 'bg-transparent border-transparent text-muted-foreground opacity-40 hover:opacity-70'
                }
              `}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: getMolColor(mol) }}
              />
              {formatMolecule(mol)}
              {detection && (
                <span className={`
                  text-[10px] font-data ml-0.5
                  ${detection.detection_sigma >= 3 ? 'text-green-500' : 'text-muted-foreground'}
                `}>
                  {detection.detection_sigma.toFixed(1)}σ
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Main Chart ─────────────────────────────────────────────────── */}
      <div className="w-full" style={{ height: 360 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 24, right: 24, bottom: 30, left: 24 }}
          >
            <defs>
              <linearGradient id="spectrumGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ffffff" stopOpacity={0.15} />
                <stop offset="100%" stopColor="#ffffff" stopOpacity={0.01} />
              </linearGradient>
            </defs>

            <CartesianGrid
              strokeDasharray="3 3"
              stroke="hsl(var(--border))"
              opacity={0.3}
            />

            <XAxis
              dataKey="wavelength"
              type="number"
              domain={[wMin, wMax]}
              tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
              tickLine={{ stroke: 'hsl(var(--border))' }}
              axisLine={{ stroke: 'hsl(var(--border))' }}
              label={{
                value: 'Wavelength (μm)',
                position: 'bottom',
                offset: 12,
                fontSize: 11,
                fill: 'hsl(var(--muted-foreground))'
              }}
            />

            <YAxis
              tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
              tickLine={{ stroke: 'hsl(var(--border))' }}
              axisLine={{ stroke: 'hsl(var(--border))' }}
              label={{
                value: 'Transit Depth (ppm)',
                angle: -90,
                position: 'insideLeft',
                offset: -8,
                fontSize: 11,
                fill: 'hsl(var(--muted-foreground))'
              }}
            />

            <Tooltip content={<CustomTooltip />} />

            {/* HITRAN molecular reference lines */}
            {visibleHitran.map((h, i) => (
              <ReferenceLine
                key={`h-${i}`}
                x={h.wavelength_um}
                stroke={getMolColor(h.molecule)}
                strokeDasharray="2 4"
                strokeOpacity={0.35}
                strokeWidth={1}
              />
            ))}

            {/* Spectrum area fill */}
            <Area
              dataKey="depth"
              fill="url(#spectrumGrad)"
              stroke="#ffffff"
              strokeWidth={1.5}
              dot={false}
              activeDot={{
                r: 4,
                fill: '#ffffff',
                stroke: 'hsl(var(--background))',
                strokeWidth: 2
              }}
              isAnimationActive={false}
            />

            {/* Error bars on scatter points */}
            <Scatter
              data={chartData.filter((_, i) => i % 3 === 0)} // Show every 3rd for clarity
              fill="#ffffff"
              fillOpacity={0.6}
              r={2}
              isAnimationActive={false}
            >
              <ErrorBar
                dataKey="errorY"
                width={0}
                strokeWidth={1}
                stroke="#ffffff"
                opacity={0.4}
                direction="y"
              />
            </Scatter>

            {/* Detection markers — larger colored dots at detection wavelengths */}
            {detectionMarkers.map((dm, i) => (
              <ReferenceLine
                key={`det-${i}`}
                x={dm.wavelength}
                stroke={dm.color}
                strokeWidth={2}
                strokeOpacity={0.7}
                label={{
                  value: formatMolecule(dm.molecule),
                  position: 'top',
                  fontSize: 9,
                  fontWeight: 600,
                  fill: dm.color,
                  offset: 8,
                }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ── Legend ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-center gap-6 text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-[2px] bg-[hsl(var(--chart-1))]" />
          <span>Transit spectrum</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-[2px] border-t border-dashed border-muted-foreground" />
          <span>HITRAN line positions</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-[2px] bg-current opacity-70" />
          <span>Confirmed detection</span>
        </div>
      </div>
    </div>
  )
}
