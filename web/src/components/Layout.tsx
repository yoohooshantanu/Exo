import { Outlet, useLocation, Link } from 'react-router-dom'
import { Orbit, Compass, Telescope, BarChart3, Bell, ShieldCheck } from 'lucide-react'

const navItems = [
  { to: '/', label: 'Overview', icon: Compass },
  { to: '/planets', label: 'Catalog', icon: Telescope },
  { to: '/stars', label: 'Star Map', icon: Orbit },
  { to: '/rankings', label: 'Rankings', icon: BarChart3 },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/validation', label: 'Validation', icon: ShieldCheck },
]

export default function Layout() {
  const { pathname } = useLocation()
  const isStarMap = pathname === '/stars'

  return (
    <div className="min-h-screen bg-[#07070a] text-zinc-200 antialiased selection:bg-zinc-800 selection:text-white flex flex-col font-sans">
      {/* Modern High-Precision Top Header */}
      <header className="sticky top-0 z-50 h-13 border-b border-zinc-800/80 bg-[#07070a]/90 backdrop-blur-xl px-4 sm:px-6">
        <div className="max-w-7xl mx-auto h-full flex items-center justify-between gap-6">
          {/* Logo / Brand */}
          <Link to="/" className="flex items-center gap-3 shrink-0 group">
            <div className="size-6 rounded-md bg-zinc-900 border border-zinc-700/80 flex items-center justify-center text-zinc-300 transition-colors group-hover:border-zinc-500 group-hover:text-white">
              <span className="text-[11px] font-mono font-semibold tracking-tighter">Ex</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-medium text-sm text-zinc-100 tracking-tight">ExoDiscovery</span>
            </div>
          </Link>

          {/* Minimal Clean Navigation */}
          <nav className="flex items-center gap-1 sm:gap-1.5">
            {navItems.map((item) => {
              const active = pathname === item.to || (item.to !== '/' && pathname.startsWith(item.to))
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all ${
                    active
                      ? 'bg-zinc-800/80 text-white shadow-sm'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/60'
                  }`}
                >
                  <item.icon className="size-3.5" />
                  <span className="hidden md:inline">{item.label}</span>
                </Link>
              )
            })}
          </nav>

          {/* Status Indicator */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-mono text-zinc-400">
            <span className="size-1.5 rounded-full bg-emerald-500" />
            <span className="text-[11px]">NASA Archive Synced</span>
          </div>
        </div>
      </header>

      {/* Page Content */}
      <main className={`flex-1 ${isStarMap ? 'w-full' : 'max-w-7xl mx-auto w-full px-4 sm:px-6 py-6'}`}>
        <Outlet />
      </main>

      {/* Minimal Footer */}
      {!isStarMap && (
        <footer className="border-t border-zinc-800/60 py-5 px-6 text-center text-xs text-zinc-400 font-mono">
          <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
            <span>Autonomous Exoplanet Screening &amp; Decision Layer</span>
            <span>6,467 Confirmed Systems &bull; JWST Cycle 1–3 Allocations</span>
          </div>
        </footer>
      )}
    </div>
  )
}
