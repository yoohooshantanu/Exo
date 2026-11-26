import { useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BarChart, Bar, XAxis, CartesianGrid } from 'recharts'
import { usePosterior } from '@/hooks/useApi'
import { Skeleton } from '@/components/ui/skeleton'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import type { ChartConfig } from '@/components/ui/chart'
import type { AtmosphericRetrieval } from '@/types'
import { api } from '@/lib/api'
import {
  Download,
  CheckCircle2,
  AlertTriangle,
  Info,
  Layers,
  Cpu,
  FileJson,
  AlertCircle,
  Database,
} from 'lucide-react'

const chartConfig = {
  probability: { label: 'Probability', color: 'var(--chart-1)' },
} satisfies ChartConfig

interface PosteriorPlotsProps {
  retrievalId: string
  retrieval?: AtmosphericRetrieval
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

function renderStatusBadge(status?: string) {
  switch (status) {
    case 'reproducibility_verified':
      return (
        <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 gap-1.5 py-1 px-2.5">
          <CheckCircle2 className="w-3.5 h-3.5" /> Reproducibility Verified
        </Badge>
      )
    case 'convergence_not_established':
      return (
        <Badge variant="destructive" className="gap-1.5 py-1 px-2.5">
          <AlertTriangle className="w-3.5 h-3.5" /> Convergence Not Established
        </Badge>
      )
    case 'reproducibility_metadata_incomplete':
      return (
        <Badge variant="outline" className="text-amber-500 border-amber-500/30 gap-1.5 py-1 px-2.5">
          <AlertCircle className="w-3.5 h-3.5" /> Metadata Incomplete
        </Badge>
      )
    case 'configuration_recorded':
      return (
        <Badge variant="secondary" className="gap-1.5 py-1 px-2.5">
          <Info className="w-3.5 h-3.5" /> Configuration Recorded
        </Badge>
      )
    case 'execution_completed':
      return (
        <Badge variant="outline" className="text-blue-400 border-blue-500/30 gap-1.5 py-1 px-2.5">
          <CheckCircle2 className="w-3.5 h-3.5" /> Execution Completed (Reproducibility Unverified)
        </Badge>
      )
    default:
      return <Badge variant="outline">Status Recorded</Badge>
  }
}

export function PosteriorPlots({ retrievalId, retrieval }: PosteriorPlotsProps) {
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
  const opacities = retrieval?.opacity_provenance ?? []
  const priors = retrieval?.priors_record ?? []
  const diagnostics = retrieval?.convergence_diagnostics
  const seed = retrieval?.random_seed ?? retrieval?.configuration_record?.sampler?.random_seed ?? 42
  const samplerName = retrieval?.sampler_name ?? 'PyMultiNest'
  const samplerVersion = retrieval?.sampler_version ?? '2.12'

  return (
    <div className="space-y-6">
      {/* ── Reproducibility & Provenance Header Card ────────────────── */}
      <Card className="border-border/60 bg-muted/15">
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-primary" />
                <CardTitle className="text-base font-semibold">Atmospheric Retrieval Provenance & Traceability</CardTitle>
              </div>
              <CardDescription className="mt-1 text-xs text-muted-foreground">
                Model inputs, opacity provenance, sampler metaparameters, and convergence diagnostics for reproducible science.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {renderStatusBadge(retrieval?.reproducibility_status)}
              <a
                href={api.getRetrievalConfigUrl(retrievalId)}
                download={`retrieval_config_${retrievalId}.json`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs font-mono">
                  <Download className="w-3.5 h-3.5" />
                  JSON Config
                </Button>
              </a>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 pt-0">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="p-2.5 rounded border bg-background/50">
              <span className="text-muted-foreground block text-[11px] uppercase tracking-wider">Model / Framework</span>
              <span className="font-semibold text-foreground">{retrieval?.model_name || 'PLATON'} (v{retrieval?.model_version || '1.0.0'})</span>
            </div>
            <div className="p-2.5 rounded border bg-background/50">
              <span className="text-muted-foreground block text-[11px] uppercase tracking-wider">Sampler & Version</span>
              <span className="font-semibold text-foreground">{samplerName} (v{samplerVersion})</span>
            </div>
            <div className="p-2.5 rounded border bg-background/50">
              <span className="text-muted-foreground block text-[11px] uppercase tracking-wider">Random Seed</span>
              <div className="flex flex-col">
                <span className="font-mono font-semibold text-primary">{seed != null ? seed : 'Unset'}</span>
                <span className="text-[10px] text-amber-500/80 block mt-0.5">API non-deterministic (MultiNest C-library)</span>
              </div>
            </div>
            <div className="p-2.5 rounded border bg-background/50">
              <span className="text-muted-foreground block text-[11px] uppercase tracking-wider">Evidence ln(Z)</span>
              <span className="font-mono font-semibold text-foreground">
                {evidence_ln_z != null ? evidence_ln_z.toFixed(2) : 'N/A'}
                {diagnostics?.evidence_err_ln_z != null ? ` ± ${diagnostics.evidence_err_ln_z.toFixed(2)}` : ''}
              </span>
            </div>
          </div>

          {/* Convergence Quality Gate Status */}
          {diagnostics ? (
            <div className="flex items-center gap-2 p-2.5 rounded border bg-background/50 text-xs">
              <span className="text-muted-foreground uppercase tracking-wider text-[11px]">Convergence Status:</span>
              {diagnostics.converged ? (
                <span className="text-emerald-400 font-medium">Statistical Quality Gate Passed (ESS: {diagnostics.effective_sample_size?.toFixed(0) ?? 'N/A'})</span>
              ) : (
                <span className="text-amber-400 font-medium">Unconverged / Gate Not Passed ({diagnostics.warnings?.join('; ') || 'Diagnostics incomplete'})</span>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 p-2.5 rounded border bg-amber-500/10 border-amber-500/20 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span>Convergence diagnostics unavailable — convergence status unverified.</span>
            </div>
          )}

          {/* Diagnostic warnings if convergence not verified */}
          {diagnostics?.warnings && diagnostics.warnings.length > 0 && (
            <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400">
              <div className="flex items-center gap-2 font-medium">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>Convergence Diagnostics Warning</span>
              </div>
              <ul className="mt-1 list-disc pl-5 space-y-0.5 text-[11px]">
                {diagnostics.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Species-Level Opacity Provenance Table */}
          {opacities.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs font-medium text-foreground gap-1">
                <div className="flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-primary" />
                  <span>Species-Level Molecular & Atomic Opacity Provenance</span>
                </div>
                <span className="text-[10px] text-amber-500/90 font-normal">
                  Runtime binary unverified via internal loader; reflecting bibliographic registry metadata only
                </span>
              </div>
              <div className="rounded border overflow-x-auto">
                <Table className="text-xs">
                  <TableHeader className="bg-muted/40">
                    <TableRow>
                      <TableHead className="py-2 h-7 font-medium">Species</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Database & Source</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Line List / File ID</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Wavelength Coverage</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Loader Verification</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Known Limitations / Sensitivity</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {opacities.map((op, idx) => (
                      <TableRow key={idx} className="h-7 hover:bg-muted/20">
                        <TableCell className="font-semibold py-1.5 font-mono">{op.species}</TableCell>
                        <TableCell className="py-1.5">{op.database} ({op.source_release})</TableCell>
                        <TableCell className="py-1.5 font-mono text-[11px] text-muted-foreground">{op.line_list_or_file_id}</TableCell>
                        <TableCell className="py-1.5 text-muted-foreground">
                          {op.wavelength_range_um ? `${op.wavelength_range_um[0]} – ${op.wavelength_range_um[1]} µm` : '0.3 – 30.0 µm'}
                        </TableCell>
                        <TableCell className="py-1.5 text-[11px]">
                          {op.runtime_loader_verified ? (
                            <span className="text-emerald-400 font-mono">Loader Verified</span>
                          ) : (
                            <span className="text-amber-500/90 font-mono">Bibliographic Only</span>
                          )}
                        </TableCell>
                        <TableCell className="py-1.5 text-muted-foreground text-[11px]">
                          {op.limitations_and_notes || 'Standard continuum/line opacity'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          {/* Priors and Parameter Bounds */}
          {priors.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <Layers className="w-3.5 h-3.5 text-primary" />
                <span>Atmospheric Parameter Priors</span>
              </div>
              <div className="rounded border overflow-x-auto">
                <Table className="text-xs">
                  <TableHeader className="bg-muted/40">
                    <TableRow>
                      <TableHead className="py-2 h-7 font-medium">Parameter</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Prior Type</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Bounds / Values</TableHead>
                      <TableHead className="py-2 h-7 font-medium">Description</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {priors.map((pr, idx) => (
                      <TableRow key={idx} className="h-7 hover:bg-muted/20">
                        <TableCell className="font-semibold py-1.5 font-mono">{pr.parameter}</TableCell>
                        <TableCell className="py-1.5 capitalize">{pr.distribution}</TableCell>
                        <TableCell className="py-1.5 font-mono text-muted-foreground">
                          [{pr.lower_bound != null ? pr.lower_bound : '-∞'}, {pr.upper_bound != null ? pr.upper_bound : '+∞'}]
                        </TableCell>
                        <TableCell className="py-1.5 text-muted-foreground text-[11px]">{pr.description}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          {/* Scientific Caveat Banner */}
          <div className="text-[11px] text-muted-foreground/80 leading-relaxed bg-background/50 p-2.5 rounded border border-border/40">
            <span className="font-semibold text-foreground">Atmospheric Retrieval Reproducibility Note: </span>
            Atmospheric retrieval posteriors depend critically on assumed opacity sources, line list completeness, pressure grids, and sampler convergence.
            As emphasized by researchers (Doriann Blain, petitRADTRANS), alkali line wing broadening (Na/K), missing molecular bands, or local sampler optima
            can substantially bias inferred planetary chemical abundances and metallicity.
          </div>
        </CardContent>
      </Card>

      {/* ── Bayesian Evidence Bar ───────────────────────────────────── */}
      <div className="flex justify-between items-center bg-secondary/10 p-4 rounded-md border">
        <div>
          <h3 className="text-sm font-medium">Marginal Likelihood (Bayesian Evidence ln Z)</h3>
          <p className="text-2xl font-data tracking-tight text-foreground">
            {evidence_ln_z?.toFixed(2) ?? 'N/A'}
            {diagnostics?.evidence_err_ln_z != null && (
              <span className="text-sm font-normal text-muted-foreground ml-2">± {diagnostics.evidence_err_ln_z.toFixed(2)}</span>
            )}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground uppercase tracking-widest">Model Complexity Penalty Included</p>
          <p className="text-[11px] text-muted-foreground mt-0.5">{samples.length} posterior samples recorded</p>
        </div>
      </div>
      
      {/* ── 1D Marginalized Posterior Histograms ─────────────────────── */}
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
