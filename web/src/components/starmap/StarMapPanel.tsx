import { motion } from 'framer-motion'
import { X, ArrowLeft } from 'lucide-react'
import { spectralClass, pcToLy } from '@/lib/starmap-helpers'
import type { StarPositionItem, StarSystemResponse } from '@/types'

interface Props {
  star: StarPositionItem
  systemData: StarSystemResponse | undefined
  onClose: () => void
  viewMode: 'galaxy' | 'system'
}

export default function StarMapPanel({ star, systemData, onClose }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="fixed bottom-6 right-6 w-[340px] z-40 bg-background/80 backdrop-blur-md border border-border shadow-lg p-5 rounded-md"
    >
      <div className="flex flex-col">
        {/* Back to galaxy */}
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 text-[11px] font-mono text-muted-foreground hover:text-primary transition-colors mb-4 uppercase tracking-widest"
        >
          <ArrowLeft size={12} strokeWidth={1.5} /> BACK TO GALAXY
        </button>

        {/* Header */}
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="font-serif italic text-2xl text-foreground leading-tight m-0">
              {star.hip_name || star.id.slice(0, 12)}
            </h2>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              {star.n_planets} planet{star.n_planets !== 1 ? 's' : ''} &middot; {spectralClass(star.teff, star.spectral_type)}-type
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
          >
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>

        {/* Distance */}
        <div className="mb-4">
          <p className="text-[10px] text-muted-foreground font-mono tracking-widest uppercase">
            DISTANCE FROM EARTH
          </p>
          <p className="font-mono text-2xl text-primary mt-1">
            {pcToLy(star.distance_pc)}
            <span className="text-xs text-muted-foreground ml-1.5 lowercase">light-years</span>
          </p>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { label: 'T_EFF', val: star.teff ? `${Math.round(star.teff)} K` : '—' },
            { label: 'CLASS', val: spectralClass(star.teff, star.spectral_type) },
            { label: 'HAB SCORE', val: star.hab_score_max.toFixed(3), isAccent: true },
          ].map(({ label, val, isAccent }) => (
            <div key={label}>
              <p className="text-[10px] text-muted-foreground font-mono tracking-widest uppercase">{label}</p>
              <p className={`font-mono text-sm mt-0.5 ${isAccent ? 'text-primary' : 'text-foreground'}`}>{val}</p>
            </div>
          ))}
        </div>

        {/* Tags */}
        <div className="flex gap-1.5 flex-wrap">
          {star.has_biosig && (
            <span className="text-[10px] font-mono tracking-widest px-2 py-0.5 bg-amber-500/10 text-amber-500 border border-amber-500/30 uppercase rounded-sm">
              BIOSIGNATURE
            </span>
          )}
          {star.has_prediction && (
            <span className="text-[10px] font-mono tracking-widest px-2 py-0.5 bg-primary/10 text-primary border border-primary/30 uppercase rounded-sm">
              GAP PREDICTION
            </span>
          )}
        </div>

        {/* System planets list */}
        {systemData && systemData.planets.length > 0 && (
          <div className="mt-4 pt-3 border-t border-border">
            <p className="text-[10px] text-muted-foreground font-mono tracking-widest mb-2 uppercase">
              SYSTEM PLANETS
            </p>
            <div className="flex flex-col gap-1.5">
              {systemData.planets.map(p => (
                <div key={p.planet_name} className="flex justify-between text-xs">
                  <span className="text-foreground">{p.planet_name}</span>
                  <span className="font-mono text-muted-foreground">
                    {p.semi_major_axis_au ? `${p.semi_major_axis_au.toFixed(2)} AU` : ''}
                    {p.composite_score ? ` · ` : ''}
                    {p.composite_score && <span className="text-primary">{p.composite_score.toFixed(2)}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
