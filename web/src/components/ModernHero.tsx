import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, Shuffle, Telescope, Sparkles, ShieldCheck, Scale } from 'lucide-react'

interface ModernHeroProps {
  totalPlanets: number
  totalSpectra: number
}

// Curated high-impact follow-up targets for observation planning
const featuredPlanets = [
  { 
    name: 'TRAPPIST-1 e', 
    type: 'Cold Rocky Archetype', 
    teq: '250 K', 
    dist: '12.1 pc', 
    radius: '0.92 R⊕', 
    triage: 77.2, 
    obs: 78.7, 
    char: 100.0,
    note: 'Terrestrial surface confirmed (P_rocky = 0.95). Atmospheric CH4, CO, CO2, H2O, NH3 detected.'
  },
  { 
    name: 'LHS 1140 b', 
    type: 'Temperate Super-Earth', 
    teq: '235 K', 
    dist: '15.0 pc', 
    radius: '1.73 R⊕', 
    triage: 69.3, 
    obs: 76.9, 
    char: 79.3,
    note: 'High-density ocean world candidate in conservative HZ. Verified dynamical stability.'
  },
  { 
    name: 'TOI-700 d', 
    type: 'Temperate Terrestrial', 
    teq: '269 K', 
    dist: '31.1 pc', 
    radius: '1.14 R⊕', 
    triage: 80.0, 
    obs: 64.2, 
    char: 45.0,
    note: 'Quiescent early M-dwarf host. Negligible flaring erosion risk; ideal for Cycles 4–5.'
  },
  { 
    name: 'Kepler-442 b', 
    type: 'Super-Earth (K-Dwarf)', 
    teq: '233 K', 
    dist: '366 pc', 
    radius: '1.34 R⊕', 
    triage: 79.8, 
    obs: 42.5, 
    char: 35.0,
    note: 'Located in the orange dwarf sweet spot (stable multi-billion year magnetic environment).'
  },
  { 
    name: 'Wolf 1069 b', 
    type: 'Nearby Terrestrial', 
    teq: '250 K', 
    dist: '9.6 pc', 
    radius: '1.08 R⊕', 
    triage: 78.8, 
    obs: 58.0, 
    char: 30.0,
    note: 'Nearby non-transiting candidate ideal for high-resolution ground-based ELT spectroscopy.'
  },
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
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900/80 px-2.5 py-1 text-xs font-mono text-zinc-300"><span className="size-1.5 rounded-full bg-sky-400" /><span>Observatory Target Prioritization Engine</span></div>
            <div className="inline-flex items-center gap-1.5 rounded-md border border-zinc-800 bg-zinc-900/80 px-2.5 py-1 text-xs font-mono text-zinc-300"><span className="size-1.5 rounded-full bg-emerald-400" /><span>JWST Allocation Validated</span></div>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium tracking-tight text-white leading-tight">
            Scientific Screening &amp; Triage of Exoplanet Follow-up Targets
          </h1>

          <p className="text-sm text-zinc-400 max-w-xl leading-relaxed">
            An open-source, de-circularized decision architecture over <strong>{totalPlanets.toLocaleString()}</strong> confirmed worlds. 
            Explicitly separates geometric telescope transmission SNR from intrinsic physical surface habitability 
            (<span className="font-mono text-zinc-300">P_rocky</span> gate) and post-observation atmospheric molecular characterization.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link
              to="/planets"
              className="inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-4 py-2 text-xs font-semibold text-zinc-900 transition-transform hover:scale-[1.02] active:scale-[0.98]"
            >
              <Telescope className="size-3.5" />
              <span>Explore 6,467+ Targets</span>
            </Link>

            <Link
              to="/validation"
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-xs font-medium text-zinc-300 hover:border-zinc-700 hover:text-white transition-colors"
            >
              <Scale className="size-3.5 text-zinc-400" />
              <span>JWST Allocation Study</span>
              <ArrowUpRight className="size-3 text-zinc-500" />
            </Link>
          </div>
        </div>

        {/* Right Column: Interactive Minimal Planetary Radar / Inspector */}
        <div className="lg:col-span-5 border border-zinc-800/80 rounded-lg bg-zinc-900/30 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
              <Telescope className="size-3 text-zinc-400" />
              <span>Featured Follow-Up Target</span>
            </div>
            <button
              onClick={cyclePlanet}
              className="inline-flex items-center gap-1.5 text-[11px] font-mono text-zinc-400 hover:text-white transition-colors bg-zinc-800/60 hover:bg-zinc-800 px-2 py-1 rounded"
              title="Inspect another featured system"
            >
              <Shuffle className="size-3" />
              <span>Next Candidate</span>
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
              <p className="text-xs text-zinc-400 mt-0.5">{planet.type} &bull; {planet.dist} &bull; {planet.radius}</p>
              <p className="text-[11px] text-zinc-400 mt-1 italic leading-snug">{planet.note}</p>
            </div>

            {/* Three Decoupled Indices Display */}
            <div className="grid grid-cols-3 gap-2 pt-2 border-t border-zinc-800/60 font-mono text-xs">
              <div className="p-2 rounded bg-zinc-950/60 border border-zinc-800/50">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-400">
                  <span className="size-1.5 rounded-full bg-sky-400/90" />
                  <span>Observability</span>
                </div>
                <span className="text-base font-medium text-zinc-100 mt-0.5 block">{planet.obs.toFixed(1)}</span>
                <span className="text-[9px] text-zinc-500 block">Geometric SNR</span>
              </div>
              <div className="p-2 rounded bg-zinc-950/60 border border-zinc-800/50">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-400">
                  <span className="size-1.5 rounded-full bg-emerald-400/90" />
                  <span>Physical Triage</span>
                </div>
                <span className="text-base font-medium text-zinc-100 mt-0.5 block">{planet.triage.toFixed(1)}</span>
                <span className="text-[9px] text-zinc-500 block">P_rocky &times; ESI</span>
              </div>
              <div className="p-2 rounded bg-zinc-950/60 border border-zinc-800/50">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-400">
                  <span className="size-1.5 rounded-full bg-indigo-400/90" />
                  <span>Characterized</span>
                </div>
                <span className="text-base font-medium text-zinc-100 mt-0.5 block">{planet.char.toFixed(1)}</span>
                <span className="text-[9px] text-zinc-500 block">HITRAN Spectra</span>
              </div>
            </div>

            <div className="pt-2 flex items-center justify-between text-xs text-zinc-400 font-mono">
              <span>Eq. Temp: <strong className="text-zinc-200">{planet.teq}</strong></span>
              <Link
                to={`/planets/${encodeURIComponent(planet.name)}`}
                className="text-xs text-zinc-300 hover:text-white transition-colors"
              >
                Inspect Full Profile &rarr;
              </Link>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
