import { motion } from 'framer-motion'
import { Sparkles, Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

interface CosmicHeroProps {
  totalPlanets: number
  totalSpectra: number
  onSurpriseMe?: () => void
}

export function CosmicHero({ totalPlanets, totalSpectra }: CosmicHeroProps) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-indigo-950/40 via-purple-950/20 to-black/60 p-6 md:p-8 backdrop-blur-xl shadow-2xl mb-8">
      {/* Background radial gradient spotlight */}
      <div className="pointer-events-none absolute -top-24 -left-24 size-96 rounded-full bg-cyan-500/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-24 -right-24 size-96 rounded-full bg-purple-600/15 blur-3xl" />

      <div className="relative z-10 flex flex-col md:flex-row items-center justify-between gap-8">
        <div className="space-y-4 max-w-xl text-center md:text-left">
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3.5 py-1 text-xs font-medium text-cyan-300 shadow-[0_0_15px_rgba(6,182,212,0.25)]"
          >
            <Sparkles className="size-3.5 animate-spin [animation-duration:8s]" />
            <span>Exo Planetary Observatory &bull; Live Intelligence</span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight text-white font-serif"
          >
            Explore <span className="bg-gradient-to-r from-cyan-400 via-sky-300 to-purple-400 bg-clip-text text-transparent">Alien Worlds</span> Beyond Our Stars
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="text-sm md:text-base text-zinc-300 leading-relaxed"
          >
            Synthesizing <strong>{totalPlanets.toLocaleString() || '6,400+'}</strong> confirmed worlds across habitability metrics, flux-aware XUV retention models, and JWST Cycle 1–3 spectroscopic detections.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="flex flex-wrap items-center justify-center md:justify-start gap-3 pt-2"
          >
            <Link
              to="/stars"
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/25 transition-all hover:scale-105 hover:shadow-cyan-500/40 active:scale-95"
            >
              <Compass className="size-4" />
              <span>Launch 3D Star Map</span>
            </Link>

            <Link
              to="/planets"
              className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/5 px-5 py-2.5 text-sm font-medium text-zinc-200 backdrop-blur-md transition-all hover:bg-white/10 hover:border-white/30 active:scale-95"
            >
              <span>Exoplanet Catalog ({totalPlanets})</span>
            </Link>
          </motion.div>
        </div>

        {/* 3D-Style Playful Floating Orbital Visualizer */}
        <div className="relative size-60 sm:size-72 shrink-0 flex items-center justify-center">
          {/* Central Pulsing Star */}
          <motion.div
            animate={{
              scale: [1, 1.08, 1],
              boxShadow: [
                '0 0 40px rgba(245, 158, 11, 0.4), inset 0 0 20px #fbbf24',
                '0 0 70px rgba(245, 158, 11, 0.7), inset 0 0 30px #f59e0b',
                '0 0 40px rgba(245, 158, 11, 0.4), inset 0 0 20px #fbbf24',
              ],
            }}
            transition={{ repeat: Infinity, duration: 4, ease: 'easeInOut' }}
            className="size-16 sm:size-20 rounded-full bg-gradient-to-br from-amber-200 via-yellow-400 to-amber-600 border border-yellow-200 z-10 cursor-pointer"
            title="Host Star"
          />

          {/* Orbit Ring 1 */}
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ repeat: Infinity, duration: 14, ease: 'linear' }}
            className="absolute size-36 sm:size-44 rounded-full border border-cyan-400/25 border-dashed"
          >
            {/* Rocky Planet */}
            <motion.div
              whileHover={{ scale: 1.5 }}
              className="absolute -top-2.5 left-1/2 -translate-x-1/2 size-5 rounded-full bg-gradient-to-tr from-cyan-600 via-sky-400 to-teal-200 shadow-[0_0_12px_rgba(56,189,248,0.8)] border border-white/40 cursor-pointer"
              title="Habitable Zone World"
            />
          </motion.div>

          {/* Orbit Ring 2 */}
          <motion.div
            animate={{ rotate: -360 }}
            transition={{ repeat: Infinity, duration: 24, ease: 'linear' }}
            className="absolute size-52 sm:size-64 rounded-full border border-purple-400/20"
          >
            {/* Gas Giant with Ring */}
            <motion.div
              whileHover={{ scale: 1.4 }}
              className="absolute -bottom-3.5 left-1/2 -translate-x-1/2 size-7 rounded-full bg-gradient-to-br from-purple-500 via-pink-400 to-amber-300 shadow-[0_0_15px_rgba(168,85,247,0.7)] border border-white/30 cursor-pointer"
              title="Gas Giant / Sub-Neptune"
            />
          </motion.div>

          {/* Orbit Ring 3 - Outer faint orbit */}
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ repeat: Infinity, duration: 40, ease: 'linear' }}
            className="absolute size-64 sm:size-72 rounded-full border border-white/10"
          >
            {/* Cold outer planet */}
            <div className="absolute top-1/2 -right-1.5 -translate-y-1/2 size-3.5 rounded-full bg-blue-300 shadow-[0_0_8px_rgba(147,197,253,0.9)]" />
          </motion.div>
        </div>
      </div>
    </div>
  )
}
