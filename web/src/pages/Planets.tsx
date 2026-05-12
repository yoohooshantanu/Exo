import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { usePlanets } from '@/hooks/useApi'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import PlanetDetailPanel from '@/components/PlanetDetailPanel'
import AnimatedNumber from '@/components/AnimatedNumber'
import { Search } from 'lucide-react'
import type { PlanetListItem } from '@/types'

export default function Planets() {
  const [search, setSearch] = useState('')
  const [pages, setPages] = useState<PlanetListItem[]>([])
  const [page, setPage] = useState(1)
  const [selectedPlanet, setSelectedPlanet] = useState<string | null>(null)
  const loaderRef = useRef<HTMLDivElement>(null)

  const { data, isLoading } = usePlanets({ page, page_size: 50 })

  useEffect(() => {
    if (data?.items) {
      setPages(prev => {
        if (page === 1) return data.items
        const existing = new Set(prev.map(p => p.planet_name))
        return [...prev, ...data.items.filter(p => !existing.has(p.planet_name))]
      })
    }
  }, [data, page])

  useEffect(() => {
    const el = loaderRef.current
    if (!el) return
    const obs = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && data && page < data.pages) setPage(p => p + 1)
    }, { threshold: 0.1 })
    obs.observe(el)
    return () => obs.disconnect()
  }, [data, page])

  const filtered = useMemo(() => {
    if (!search) return pages
    const q = search.toLowerCase()
    return pages.filter(p =>
      p.planet_name.toLowerCase().includes(q) ||
      p.hostname?.toLowerCase().includes(q)
    )
  }, [pages, search])

  return (
    <>
      <div className="space-y-6">
        <div className="flex items-center justify-between animate-fade-up">
          <h1 className="text-3xl font-light tracking-tight">Planet Catalog</h1>
          <span className="font-data text-xs text-muted-foreground">
            {data?.total?.toLocaleString() ?? '—'} confirmed
          </span>
        </div>

        <div className="relative max-w-sm animate-fade-up delay-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter planets..."
            className="pl-10"
          />
        </div>

        <Card className="animate-fade-up delay-2">
          <CardContent className="p-0 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs uppercase tracking-wider">Planet</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider">Host</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider">Type</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Radius</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Mass</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Period</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Score</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Year</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && page === 1 && Array.from({ length: 12 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 8 }).map((_, j) => (
                      <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))}
                {filtered.map((planet, i) => (
                  <TableRow
                    key={planet.planet_name}
                    className="cursor-pointer animate-scan-line"
                    style={{ animationDelay: `${Math.min(i, 20) * 30}ms` }}
                    onClick={() => setSelectedPlanet(planet.planet_name)}
                  >
                    <TableCell>
                      <Link
                        to={`/planets/${encodeURIComponent(planet.planet_name)}`}
                        className="text-foreground hover:text-chart-1 transition-colors"
                        onClick={e => e.stopPropagation()}
                      >
                        {planet.planet_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{planet.hostname}</TableCell>
                    <TableCell>
                      {planet.cluster_name ? (
                        <Badge variant="secondary" className="text-xs font-normal">{planet.cluster_name}</Badge>
                      ) : '—'}
                    </TableCell>
                    <TableCell className="text-right font-data">{planet.radius_earth?.toFixed(2) ?? '—'}</TableCell>
                    <TableCell className="text-right font-data">{planet.mass_earth?.toFixed(2) ?? '—'}</TableCell>
                    <TableCell className="text-right font-data">{planet.period_days?.toFixed(1) ?? '—'}</TableCell>
                    <TableCell className="text-right">
                      {planet.composite_score != null ? (
                        <span className="font-data text-chart-1">{planet.composite_score.toFixed(3)}</span>
                      ) : '—'}
                    </TableCell>
                    <TableCell className="text-right font-data text-muted-foreground">
                      {planet.discovery_year}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div ref={loaderRef} className="h-8" />
            {isLoading && page > 1 && (
              <div className="p-4"><Skeleton className="h-8 w-full" /></div>
            )}
          </CardContent>
        </Card>
      </div>

      <Sheet open={!!selectedPlanet} onOpenChange={() => setSelectedPlanet(null)}>
        <SheetContent className="overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{selectedPlanet}</SheetTitle>
          </SheetHeader>
          {selectedPlanet && <PlanetDetailPanel name={selectedPlanet} />}
        </SheetContent>
      </Sheet>
    </>
  )
}
