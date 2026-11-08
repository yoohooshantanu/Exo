import type { StarPositionItem } from '@/types'

interface Props {
  star: StarPositionItem
  x: number
  y: number
}

export default function StarMapTooltip({ star, x, y }: Props) {
  return (
    <div
      className="fixed z-40 pointer-events-none bg-background/90 border border-border px-2.5 py-1.5 text-xs text-foreground font-sans opacity-100 transition-opacity duration-100"
      style={{
        left: x + 14,
        top: y - 10,
      }}
    >
      <span className="font-mono font-medium">
        {star.hip_name || star.id.slice(0, 8)}
      </span>
      {star.n_planets > 0 && (
        <span className="text-muted-foreground ml-2 font-mono text-[11px]">
          {star.n_planets} planet{star.n_planets !== 1 ? 's' : ''}
        </span>
      )}
      {star.distance_pc && (
        <span className="text-muted-foreground ml-2 font-mono text-[10px] opacity-70">
          {(star.distance_pc * 3.26156).toFixed(0)} ly
        </span>
      )}
    </div>
  )
}
