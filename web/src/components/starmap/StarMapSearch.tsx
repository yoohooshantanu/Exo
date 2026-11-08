import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, X, Filter } from 'lucide-react'
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

  return (
    <div className="fixed bottom-6 left-6 z-30">
      {/* Filter button */}
      <div className="mb-2">
        <button
          className="flex items-center justify-center w-8 h-8 bg-background border border-border text-muted-foreground hover:text-foreground transition-colors cursor-pointer mb-1"
          onClick={() => setShowFilters(!showFilters)}
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
              className="bg-background border border-border p-3 mb-1 w-[200px]"
            >
              {(['habitable', 'biosig', 'predictions'] as const).map(key => (
                <label
                  key={key}
                  className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer font-mono mb-1.5"
                >
                  <input
                    type="checkbox"
                    checked={filters[key]}
                    onChange={() => setFilters(f => ({ ...f, [key]: !f[key] }))}
                    className="accent-primary"
                  />
                  {key === 'habitable' ? 'HABITABLE (>0.7)' : key === 'biosig' ? 'BIOSIGNATURE' : 'GAP PREDICTIONS'}
                </label>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Search input */}
      <div 
        className={`flex items-center gap-2 px-3 py-2 bg-background border-b transition-all duration-200 ease-in-out font-sans ${focused ? 'border-primary w-[320px]' : 'border-border w-[240px]'}`}
      >
        <Search size={14} className="text-muted-foreground" strokeWidth={1.5} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          placeholder="Search stars..."
          className="bg-transparent border-none outline-none text-[13px] text-foreground flex-1 font-sans"
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            className="bg-transparent border-none cursor-pointer text-muted-foreground p-0"
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
            className="bg-background border border-t-0 border-border max-h-[200px] overflow-y-auto"
          >
            {results.map(star => (
              <button
                key={star.id}
                onClick={() => { onSelect(star); setQuery('') }}
                className="flex items-center justify-between w-full px-3 py-2 bg-transparent border-none cursor-pointer text-[13px] text-foreground font-sans text-left transition-colors hover:bg-muted"
              >
                <span>{star.hip_name || star.id.slice(0, 8)}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
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
