import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { ParamProvenance } from '@/types'

const STATUS_CONFIG = {
  measured: {
    color: 'bg-emerald-500',
    label: 'Measured',
    description: 'Direct observation',
  },
  derived: {
    color: 'bg-blue-500',
    label: 'Derived',
    description: 'Computed from other parameters',
  },
  imputed: {
    color: 'bg-amber-500',
    label: 'Imputed',
    description: 'Estimated from group statistics',
  },
  heuristic: {
    color: 'bg-zinc-400',
    label: 'Heuristic',
    description: 'Model output — not validated',
  },
} as const

interface ProvenanceBadgeProps {
  provenance?: ParamProvenance
  className?: string
}

export function ProvenanceBadge({ provenance, className = '' }: ProvenanceBadgeProps) {
  if (!provenance) return null

  const config = STATUS_CONFIG[provenance.status] ?? STATUS_CONFIG.heuristic
  const source = provenance.source ?? config.description
  const uncStr = provenance.uncertainty
    ? ` · ±[${provenance.uncertainty[0]?.toFixed(3)}, ${provenance.uncertainty[1]?.toFixed(3)}]`
    : ''

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={`inline-block w-2 h-2 rounded-full ${config.color} cursor-help ${className}`}
            aria-label={`${config.label}: ${source}`}
          />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-xs">
          <p className="font-semibold">{config.label}</p>
          <p className="text-muted-foreground">{source}{uncStr}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
