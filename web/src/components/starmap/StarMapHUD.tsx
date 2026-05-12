import { useState } from 'react'
import { motion } from 'framer-motion'
import { T } from '@/lib/starmap-helpers'

interface Props {
  starCount: number | undefined
  canvasReady: boolean
}

export default function StarMapHUD({ starCount, canvasReady }: Props) {
  const [is3D] = useState(true)
  const mono = 'var(--exo-font-mono)'

  return (
    <>
      {/* Full-screen fade-in from black */}
      <motion.div
        initial={{ opacity: 1 }}
        animate={{ opacity: canvasReady ? 0 : 1 }}
        transition={{ duration: 1.5, ease: 'easeOut' }}
        style={{
          position: 'fixed',
          inset: 0,
          background: T.void,
          zIndex: 20,
          pointerEvents: 'none',
        }}
      />

      {/* Top-right: star count + 3D toggle */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.6, duration: 0.4 }}
        style={{
          position: 'fixed',
          top: 68,
          right: 24,
          zIndex: 30,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <span style={{ fontFamily: mono, fontSize: 12, color: T.text2 }}>
          {starCount?.toLocaleString() ?? '—'} stars
        </span>
        <span style={{ color: T.text3, fontSize: 11 }}>·</span>
        <span style={{
          fontFamily: mono,
          fontSize: 11,
          color: is3D ? T.accent : T.text3,
          letterSpacing: '0.06em',
          cursor: 'default',
        }}>
          3D VIEW
        </span>
      </motion.div>

      {/* Sweep loading line — visible until canvas ready */}
      {!canvasReady && (
        <div style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          height: 1,
          zIndex: 25,
          overflow: 'hidden',
        }}>
          <div style={{
            width: '100%',
            height: '100%',
            background: `linear-gradient(90deg, transparent, ${T.borderHi}, transparent)`,
            animation: 'sweep 1.5s linear infinite',
          }} />
          <style>{`
            @keyframes sweep {
              0% { transform: translateX(-100%); }
              100% { transform: translateX(100%); }
            }
          `}</style>
        </div>
      )}
    </>
  )
}
