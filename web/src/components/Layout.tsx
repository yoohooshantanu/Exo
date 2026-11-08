import { Outlet, useLocation, Link } from 'react-router-dom'
import { Orbit, Globe, Map, Telescope, BarChart3, AlertTriangle, ShieldCheck } from 'lucide-react'
import { CosmicStarfield } from '@/components/CosmicStarfield'

const navItems = [
  { to: '/', label: 'Dashboard', icon: Globe },
  { to: '/stars', label: 'Star Map', icon: Map },
  { to: '/planets', label: 'Catalog', icon: Telescope },
  { to: '/rankings', label: 'Rankings', icon: BarChart3 },
  { to: '/alerts', label: 'Alerts', icon: AlertTriangle },
  { to: '/validation', label: 'Validation', icon: ShieldCheck },
]

export default function Layout() {
  const { pathname } = useLocation()
  const isStarMap = pathname === '/stars'

  return (
    <div className="relative flex min-h-screen flex-col max-w-7xl mx-auto w-full">
      {/* Dynamic Cosmic Starfield Background */}
      <CosmicStarfield />

      {/* Top navbar */}
      <header className="sticky top-0 z-50 flex h-14 items-center border-b border-white/10 bg-background/80 backdrop-blur-md px-4 gap-6">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2.5 shrink-0 group">
          <div className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-tr from-cyan-500 to-purple-600 text-white shadow-[0_0_15px_rgba(6,182,212,0.4)] transition-transform group-hover:scale-110">
            <Orbit className="size-4 animate-spin [animation-duration:12s]" />
          </div>
          <span className="font-bold text-sm tracking-wide bg-gradient-to-r from-white via-zinc-200 to-cyan-300 bg-clip-text text-transparent hidden sm:inline">
            ExoDiscovery
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1.5">
          {navItems.map((item) => {
            const active = pathname === item.to ||
              (item.to !== '/' && pathname.startsWith(item.to))
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`relative flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-200 ${active
                    ? 'bg-white/10 text-cyan-300 shadow-sm border border-cyan-500/20'
                    : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
              >
                <item.icon className="size-4" />
                <span className="hidden md:inline">{item.label}</span>
                {active && (
                  <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-cyan-400 rounded-full shadow-[0_0_8px_#38bdf8]" />
                )}
              </Link>
            )
          })}
        </nav>
      </header>

      {/* Page content */}
      <main className={`relative z-10 ${isStarMap ? 'flex-1' : 'flex-1 p-4 md:p-6'}`}>
        <Outlet />
      </main>
    </div>
  )
}
