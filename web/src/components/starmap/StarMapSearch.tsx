import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, X, Filter } from 'lucide-react'
import { T } from '@/lib/starmap-helpers'
import type { StarPositionItem } from '@/types'

interface Props {
  stars: StarPositionItem[]
  onSelect: (star: StarPositionItem) => void
}

export default function StarMapSearch({ stars, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState({ habitable: false, biosig: false, predictions: false })
  const inputRef = useRef<HTMLInputElement>(null)

  const results = query
    ? stars.filter(s => s.hip_name.toLowerCase().includes(query.toLowerCase())).slice(0, 8)
    : []

  const s = {
    wrapper: {
      position: 'fixed' as const,
      bottom: 24,
      left: 24,
      zIndex: 30,
    },
    searchBox: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '8px 12px',
      background: T.base,
      borderBottom: `1px solid ${focused ? T.accent : T.border}`,
      transition: 'border-color 200ms ease, width 200ms ease',
      width: focused ? 320 : 240,
      fontFamily: 'var(--exo-font-system)',
    },
    input: {
      background: 'transparent',
      border: 'none',
      outline: 'none',
      fontSize: '13px',
      color: T.text1,
      flex: 1,
      fontFamily: 'var(--exo-font-system)',
    },
    dropdown: {
      background: T.base,
      border: `1px solid ${T.border}`,
      borderTop: 'none',
      maxHeight: 200,
      overflowY: 'auto' as const,
    },
    result: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      width: '100%',
      padding: '8px 12px',
      background: 'transparent',
      border: 'none',
      cursor: 'pointer',
      fontSize: '13px',
      color: T.text1,
      fontFamily: 'var(--exo-font-system)',
      transition: 'background 100ms',
      textAlign: 'left' as const,
    },
    filterBtn: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 32,
      height: 32,
      background: T.base,
      border: `1px solid ${T.border}`,
      cursor: 'pointer',
      color: T.text2,
      transition: 'color 120ms',
      marginBottom: 4,
    },
    filterPanel: {
      background: T.base,
      border: `1px solid ${T.border}`,
      padding: 12,
      marginBottom: 4,
      width: 200,
    },
  }

  return (
    <div style={s.wrapper}>
      {/* Filter button */}
      <div style={{ marginBottom: 8 }}>
        <button
          style={s.filterBtn}
          onClick={() => setShowFilters(!showFilters)}
          onMouseEnter={e => (e.currentTarget.style.color = T.text1)}
          onMouseLeave={e => (e.currentTarget.style.color = T.text2)}
        >
          <Filter size={14} strokeWidth={1.5} />
        </button>
        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.15 }}
              style={s.filterPanel}
            >
              {(['habitable', 'biosig', 'predictions'] as const).map(key => (
                <label
                  key={key}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    fontSize: '12px', color: T.text2, cursor: 'pointer',
                    fontFamily: 'var(--exo-font-mono)',
                    marginBottom: 6,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={filters[key]}
                    onChange={() => setFilters(f => ({ ...f, [key]: !f[key] }))}
                    style={{ accentColor: T.accent }}
                  />
                  {key === 'habitable' ? 'HABITABLE (>0.7)' : key === 'biosig' ? 'BIOSIGNATURE' : 'GAP PREDICTIONS'}
                </label>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Search input */}
      <div style={s.searchBox}>
        <Search size={14} color={T.text2} strokeWidth={1.5} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          placeholder="Search stars..."
          style={s.input}
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: T.text2, padding: 0 }}
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* Results dropdown */}
      <AnimatePresence>
        {query && results.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.1 }}
            style={s.dropdown}
          >
            {results.map(star => (
              <button
                key={star.id}
                style={s.result}
                onClick={() => { onSelect(star); setQuery('') }}
                onMouseEnter={e => (e.currentTarget.style.background = T.raised)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <span>{star.hip_name || star.id.slice(0, 8)}</span>
                <span style={{ fontFamily: 'var(--exo-font-mono)', fontSize: '11px', color: T.text3 }}>
                  {star.n_planets > 0 ? `${star.n_planets}p` : ''}
                  {star.distance_pc ? ` · ${(star.distance_pc * 3.26156).toFixed(0)} ly` : ''}
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
