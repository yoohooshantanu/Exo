import { Outlet, useLocation, Link } from 'react-router-dom'
import { Orbit, Globe, Map, Telescope, BarChart3, AlertTriangle } from 'lucide-react'

const navItems = [
  { to: '/', label: 'Dashboard', icon: Globe },
  { to: '/stars', label: 'Star Map', icon: Map },
  { to: '/planets', label: 'Catalog', icon: Telescope },
  { to: '/rankings', label: 'Rankings', icon: BarChart3 },
  { to: '/alerts', label: 'Alerts', icon: AlertTriangle },
]

export default function Layout() {
  const { pathname } = useLocation()
  const isStarMap = pathname === '/stars'

  return (
    <div className="flex min-h-screen flex-col">
      {/* Top navbar */}
      <header className="sticky top-0 z-50 flex h-12 items-center border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-4 gap-6">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2 shrink-0">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Orbit className="size-3.5" />
          </div>
          <span className="font-semibold text-sm hidden sm:inline">ExoDiscovery</span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const active = pathname === item.to ||
              (item.to !== '/' && pathname.startsWith(item.to))
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                }`}
              >
                <item.icon className="size-3.5" />
                <span className="hidden md:inline">{item.label}</span>
              </Link>
            )
          })}
        </nav>
      </header>

      {/* Page content */}
      <main className={isStarMap ? 'flex-1' : 'flex-1 p-4 md:p-6'}>
        <Outlet />
      </main>
    </div>
  )
}
