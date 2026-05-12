import { motion } from 'framer-motion'
import { X, ArrowLeft } from 'lucide-react'
import { T, spectralClass, pcToLy } from '@/lib/starmap-helpers'
import type { StarPositionItem, StarSystemResponse } from '@/types'

interface Props {
  star: StarPositionItem
  systemData: StarSystemResponse | undefined
  onClose: () => void
  viewMode: 'galaxy' | 'system'
}

export default function StarMapPanel({ star, systemData, onClose }: Props) {
  const mono = 'var(--exo-font-mono)'
  const serif = 'var(--exo-font-serif)'

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      style={{
        position: 'fixed', bottom: 24, right: 24, width: 340, zIndex: 40,
        background: T.base, border: `1px solid ${T.border}`,
      }}
    >
      <div style={{ padding: 20 }}>
        {/* Back to galaxy */}
        <button
          onClick={onClose}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', cursor: 'pointer',
            color: T.text2, fontSize: 11, fontFamily: mono,
            marginBottom: 14, padding: 0, transition: 'color 120ms',
            letterSpacing: '0.08em',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = T.accent)}
          onMouseLeave={e => (e.currentTarget.style.color = T.text2)}
        >
          <ArrowLeft size={12} strokeWidth={1.5} /> BACK TO GALAXY
        </button>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <h2 style={{
              fontFamily: serif, fontStyle: 'italic', fontSize: 22,
              color: T.textWhite, lineHeight: 1.2, margin: 0,
            }}>
              {star.hip_name || star.id.slice(0, 12)}
            </h2>
            <p style={{ fontSize: 12, color: T.text2, fontFamily: mono, marginTop: 4 }}>
              {star.n_planets} planet{star.n_planets !== 1 ? 's' : ''} · {spectralClass(star.teff, star.spectral_type)}-type
            </p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: T.text2, padding: 4 }}
            onMouseEnter={e => (e.currentTarget.style.color = T.text1)}
            onMouseLeave={e => (e.currentTarget.style.color = T.text2)}
          >
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>

        {/* Distance */}
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontSize: 10, color: T.text3, fontFamily: mono, letterSpacing: '0.12em' }}>
            DISTANCE FROM EARTH
          </p>
          <p style={{ fontFamily: mono, fontSize: 22, color: T.accent, marginTop: 4 }}>
            {pcToLy(star.distance_pc)}
            <span style={{ fontSize: 12, color: T.text2, marginLeft: 6 }}>light-years</span>
          </p>
        </div>

        {/* Stats grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          {[
            { label: 'T_EFF', val: star.teff ? `${Math.round(star.teff)} K` : '—' },
            { label: 'CLASS', val: spectralClass(star.teff, star.spectral_type) },
            { label: 'HAB SCORE', val: star.hab_score_max.toFixed(3), isAccent: true },
          ].map(({ label, val, isAccent }) => (
            <div key={label}>
              <p style={{ fontSize: 10, color: T.text3, fontFamily: mono, letterSpacing: '0.08em' }}>{label}</p>
              <p style={{ fontFamily: mono, fontSize: 14, color: isAccent ? T.accent : T.text1, marginTop: 2 }}>{val}</p>
            </div>
          ))}
        </div>

        {/* Tags */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {star.has_biosig && (
            <span style={{
              fontSize: 10, fontFamily: mono, letterSpacing: '0.1em', padding: '2px 8px',
              background: T.amberDim, color: T.amber, border: `1px solid rgba(196,122,42,0.3)`,
            }}>BIOSIGNATURE</span>
          )}
          {star.has_prediction && (
            <span style={{
              fontSize: 10, fontFamily: mono, letterSpacing: '0.1em', padding: '2px 8px',
              background: T.accentDim, color: T.accent, border: `1px solid rgba(79,127,255,0.3)`,
            }}>GAP PREDICTION</span>
          )}
        </div>

        {/* System planets list */}
        {systemData && systemData.planets.length > 0 && (
          <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px solid ${T.borderSub}` }}>
            <p style={{ fontSize: 10, color: T.text3, fontFamily: mono, letterSpacing: '0.12em', marginBottom: 8 }}>
              SYSTEM PLANETS
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {systemData.planets.map(p => (
                <div key={p.planet_name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span style={{ color: T.text1, fontFamily: 'var(--exo-font-system)' }}>{p.planet_name}</span>
                  <span style={{ fontFamily: mono, color: T.text2 }}>
                    {p.semi_major_axis_au ? `${p.semi_major_axis_au.toFixed(2)} AU` : ''}
                    {p.composite_score ? ` · ` : ''}
                    {p.composite_score && <span style={{ color: T.accent }}>{p.composite_score.toFixed(2)}</span>}
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
