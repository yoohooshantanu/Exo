import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, Shuffle, Telescope, Sparkles } from 'lucide-react'

interface ModernHeroProps {
  totalPlanets: number
  totalSpectra: number
}

// Sample of notable confirmed exoplanets for the quick-orbit switcher
const featuredPlanets = [
  { name: 'TRAPPIST-1 e', type: 'Temperate Rocky', teq: '251 K', dist: '12.1 pc', triage: 82.4, obs: 78.1 },
  { name: 'LHS 1140 b', type: 'Super-Earth', teq: '235 K', dist: '15.0 pc', triage: 74.0, obs: 84.5 },
  { name: 'TOI-700 d', type: 'Earth-size HZ', teq: '269 K', dist: '31.1 pc', triage: 79.8, obs: 64.2 },
  { name: 'K2-18 b', type: 'Sub-Neptune', teq: '255 K', dist: '38.0 pc', triage: 61.2, obs: 91.0 },
]

export function ModernHero({ totalPlanets }: ModernHeroProps) {
  const [selectedIdx, setSelectedIdx] = useState(0)
  const planet = featuredPlanets[selectedIdx]

  const cyclePlanet = () => {
    setSelectedIdx((prev) => (prev + 1) % featuredPlanets.length)
  }

  return (
    <div className="border border-zinc-800/80 rounded-xl bg-zinc-950/70 p-6 md:p-8 backdrop-blur-sm mb-8 transition-all">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left Column: Mission Description */}
        <div className="lg:col-span-7 space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/80 px-2.5 py-1 text-xs font-mono text-zinc-400">
            <span className="size-1.5 rounded-full bg-cyan-400 animate-pulse" />
            <span>Exoplanet Atmospheric &amp; Orbit Pipeline</span>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium tracking-tight text-white leading-tight">
            Scientific Screening of Exoplanetary Habitability
          </h1>

          <p className="text-sm text-zinc-400 max-w-xl leading-relaxed">
            De-circularized three-tier triage over <strong>{totalPlanets.toLocaleString()}</strong> confirmed worlds. 
            Separates geometric telescope observability from physical retention and post-observation atmospheric enrichment.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link
              to="/planets"
              className="inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-4 py-2 text-xs font-semibold text-zinc-900 transition-transform hover:scale-[1.02] active:scale-[0.98]"
            >
              <Telescope className="size-3.5" />
              <span>Browse Catalog</span>
            </Link>

            <Link
              to="/validation"
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-xs font-medium text-zinc-300 hover:border-zinc-700 transition-colors"
            >
              <span>JWST Allocation Validation</span>
              <ArrowUpRight className="size-3 text-zinc-500" />
            </Link>
          </div>
        </div>

        {/* Right Column: Interactive Minimal Planetary Radar / Inspector */}
        <div className="lg:col-span-5 border border-zinc-800/80 rounded-lg bg-zinc-900/30 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
              <Sparkles className="size-3 text-zinc-500" />
              <span>Featured System</span>
            </div>
            <button
              onClick={cyclePlanet}
              className="inline-flex items-center gap-1.5 text-[11px] font-mono text-zinc-400 hover:text-white transition-colors bg-zinc-800/60 hover:bg-zinc-800 px-2 py-1 rounded"
              title="Inspect another featured system"
            >
              <Shuffle className="size-3" />
              <span>Next</span>
            </button>
          </div>

          <motion.div
            key={planet.name}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="space-y-3"
          >
            <div>
              <Link
                to={`/planets/${encodeURIComponent(planet.name)}`}
                className="text-xl font-medium text-white hover:underline inline-flex items-center gap-1.5"
              >
                <span>{planet.name}</span>
                <ArrowUpRight className="size-3.5 text-zinc-500" />
              </Link>
              <p className="text-xs text-zinc-400 mt-0.5">{planet.type} &bull; {planet.dist}</p>
            </div>

            {/* Metric Bars */}
            <div className="space-y-2 pt-1 font-mono text-xs">
              <div>
                <div className="flex justify-between text-zinc-400 text-[11px] mb-1">
                  <span>Physical Triage Index</span>
                  <span className="text-zinc-200">{planet.triage}/100</span>
                </div>
                <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-zinc-300 rounded-full transition-all duration-500"
                    style={{ width: `${planet.triage}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-zinc-400 text-[11px] mb-1">
                  <span>Observability SNR</span>
                  <span className="text-zinc-200">{planet.obs}/100</span>
                </div>
                <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-zinc-500 rounded-full transition-all duration-500"
                    style={{ width: `${planet.obs}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="pt-2 border-t border-zinc-800/60 flex items-center justify-between text-xs text-zinc-400 font-mono">
              <span>Eq. Temp: <strong className="text-zinc-200">{planet.teq}</strong></span>
              <Link
                to={`/planets/${encodeURIComponent(planet.name)}`}
                className="text-xs text-zinc-300 hover:text-white transition-colors"
              >
                View Full Profile &rarr;
              </Link>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
