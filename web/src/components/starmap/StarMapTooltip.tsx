import type { StarPositionItem } from '@/types'
import { T } from '@/lib/starmap-helpers'

interface Props {
  star: StarPositionItem
  x: number
  y: number
}

export default function StarMapTooltip({ star, x, y }: Props) {
  return (
    <div
      className="fixed z-40 pointer-events-none"
      style={{
        left: x + 14,
        top: y - 10,
        background: T.overlay,
        border: `1px solid ${T.border}`,
        padding: '6px 10px',
        fontFamily: 'var(--exo-font-system)',
        fontSize: '12px',
        color: T.text1,
        opacity: 1,
        transition: 'opacity 100ms ease',
      }}
    >
      <span style={{ fontFamily: 'var(--exo-font-mono)', fontWeight: 500 }}>
        {star.hip_name || star.id.slice(0, 8)}
      </span>
      {star.n_planets > 0 && (
        <span style={{ color: T.text2, marginLeft: 8, fontFamily: 'var(--exo-font-mono)', fontSize: '11px' }}>
          {star.n_planets} planet{star.n_planets !== 1 ? 's' : ''}
        </span>
      )}
      {star.distance_pc && (
        <span style={{ color: T.text3, marginLeft: 8, fontFamily: 'var(--exo-font-mono)', fontSize: '10px' }}>
          {(star.distance_pc * 3.26156).toFixed(0)} ly
        </span>
      )}
    </div>
  )
}
