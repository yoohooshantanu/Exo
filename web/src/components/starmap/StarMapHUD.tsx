import { useState } from 'react'
import { motion } from 'framer-motion'

interface Props {
  starCount: number | undefined
  canvasReady: boolean
}

export default function StarMapHUD({ starCount, canvasReady }: Props) {
  const [is3D] = useState(true)

  return (
    <>
      {/* Full-screen fade-in from black */}
      <motion.div
        initial={{ opacity: 1 }}
        animate={{ opacity: canvasReady ? 0 : 1 }}
        transition={{ duration: 1.5, ease: 'easeOut' }}
        className="fixed inset-0 bg-[#06080a] z-20 pointer-events-none"
      />

      {/* Top-right: star count + 3D toggle */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.6, duration: 0.4 }}
        className="fixed top-[68px] right-6 z-30 flex items-center gap-3"
      >
        <span className="font-mono text-xs text-muted-foreground">
          {starCount?.toLocaleString() ?? '—'} stars
        </span>
        <span className="text-[11px] text-muted-foreground/50">&middot;</span>
        <span className={`font-mono text-[11px] tracking-widest cursor-default ${is3D ? 'text-primary' : 'text-muted-foreground'}`}>
          3D VIEW
        </span>
      </motion.div>

      {/* Sweep loading line — visible until canvas ready */}
      {!canvasReady && (
        <div className="fixed bottom-0 left-0 right-0 h-px z-25 overflow-hidden">
          <div 
            className="w-full h-full" 
            style={{
              background: 'linear-gradient(90deg, transparent, hsl(var(--border)), transparent)',
              animation: 'sweep 1.5s linear infinite',
            }} 
          />
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
