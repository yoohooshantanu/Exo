import { useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { BarChart, Bar, XAxis, CartesianGrid } from 'recharts'
import { usePosterior } from '@/hooks/useApi'
import { Skeleton } from '@/components/ui/skeleton'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import type { ChartConfig } from '@/components/ui/chart'

const chartConfig = {
  probability: { label: 'Probability', color: 'var(--chart-1)' },
} satisfies ChartConfig

interface PosteriorPlotsProps {
  retrievalId: string
}

// Compute 1D histogram from samples and weights
function computeHistogram(samples: number[], weights: number[], bins = 30) {
  if (!samples.length) return []
  const min = Math.min(...samples)
  const max = Math.max(...samples)
  const step = (max - min) / bins
  
  const histogram = Array.from({ length: bins }, (_, i) => ({
    binStart: min + i * step,
    binEnd: min + (i + 1) * step,
    binCenter: min + (i + 0.5) * step,
    probability: 0,
  }))

  for (let i = 0; i < samples.length; i++) {
    const val = samples[i]
    const w = weights[i] || 1
    
    let binIdx = Math.floor((val - min) / step)
    if (binIdx >= bins) binIdx = bins - 1
    if (binIdx < 0) binIdx = 0
    
    histogram[binIdx].probability += w
  }
  
  // Normalize
  const totalW = histogram.reduce((sum, b) => sum + b.probability, 0)
  if (totalW > 0) {
    histogram.forEach(b => b.probability = b.probability / totalW)
  }
  
  return histogram
}

const PARAM_LABELS: Record<string, string> = {
  'Rp': 'Planet Radius (R_jup)',
  'T': 'Temperature (K)',
  'logZ': 'Metallicity (log10)',
  'CO_ratio': 'C/O Ratio',
  'log_cloudtop_P': 'Cloud Top Pressure (log10 Pa)',
  'log_scat_factor': 'Rayleigh Scat. Factor (log10)',
}

export function PosteriorPlots({ retrievalId }: PosteriorPlotsProps) {
  const { data: posterior, isLoading, error } = usePosterior(retrievalId)

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <Skeleton key={i} className="h-[200px] w-full" />
        ))}
      </div>
    )
  }

  if (error || !posterior || !posterior.samples || !posterior.params) {
    return <div className="text-sm text-destructive">Failed to load posterior data.</div>
  }

  const { params, samples, weights, best_fit, evidence_ln_z } = posterior

  // samples is shape [n_samples, n_params]
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-secondary/10 p-4 rounded-md border">
        <div>
          <h3 className="text-sm font-medium">Bayesian Evidence (ln Z)</h3>
          <p className="text-2xl font-data tracking-tight text-foreground">{evidence_ln_z?.toFixed(2) ?? 'N/A'}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">Model Complexity Penalty Included</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {params.map((paramName: string, paramIndex: number) => {
          const paramSamples = samples.map((s: any[]) => s[paramIndex])
          const hist = computeHistogram(paramSamples, weights)
          const bestFitVal = best_fit[paramName]
          const label = PARAM_LABELS[paramName] || paramName

          return (
            <Card key={paramName} className="overflow-hidden">
              <CardHeader className="py-3 px-4 bg-muted/30 border-b">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</CardTitle>
                <div className="font-data text-xl text-foreground">
                  {bestFitVal?.toFixed(3) ?? 'N/A'}
                </div>
              </CardHeader>
              <CardContent className="p-4 pt-6 pb-2">
                <ChartContainer config={chartConfig} className="h-[120px] w-full">
                  <BarChart data={hist} margin={{ top: 0, right: 0, bottom: 0, left: 0 }} barCategoryGap={0}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.15} />
                    <XAxis 
                      dataKey="binCenter" 
                      type="number" 
                      domain={['dataMin', 'dataMax']} 
                      tickFormatter={(val) => val.toFixed(2)}
                      tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} 
                      axisLine={false}
                      tickLine={false}
                      minTickGap={20}
                    />
                    <ChartTooltip content={<ChartTooltipContent hideLabel />} cursor={{ fill: 'var(--muted)', opacity: 0.2 }} />
                    <Bar 
                      dataKey="probability" 
                      fill="var(--chart-1)" 
                      isAnimationActive={false}
                      opacity={0.8}
                    />
                  </BarChart>
                </ChartContainer>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
