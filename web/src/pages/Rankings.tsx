import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRankings } from '@/hooks/useApi'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '@/components/ui/table'
import PlanetDetailPanel from '@/components/PlanetDetailPanel'

const categories = [
  { key: 'habitable', label: 'Top Habitable' },
  { key: 'anomalous', label: 'Anomalous' },
  { key: 'biosignatures', label: 'Biosignatures' },
  { key: 'gaps', label: 'Gap Predictions' },
]

export default function Rankings() {
  const [active, setActive] = useState('habitable')
  const [selectedPlanet, setSelectedPlanet] = useState<string | null>(null)
  const { data: rankings, isLoading } = useRankings(active, 50)

  return (
    <>
      <div className="space-y-4">
        {/* Horizontal tabs row — matches reference "Outline | Past Performance | Key Personnel" style */}
        <div className="flex items-center gap-4 border-b border-border">
          {categories.map(c => (
            <button
              key={c.key}
              onClick={() => setActive(c.key)}
              className={`pb-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                active === c.key
                  ? 'border-foreground text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Table — no Card wrapper, directly on page like reference */}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">#</TableHead>
              <TableHead>Planet</TableHead>
              <TableHead>Host Star</TableHead>
              <TableHead>Classification</TableHead>
              <TableHead className="text-right">D-Score</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && Array.from({ length: 10 }).map((_, i) => (
              <TableRow key={i}>
                {Array.from({ length: 5 }).map((_, j) => (
                  <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                ))}
              </TableRow>
            ))}

            {rankings?.map((item, i) => (
              <TableRow
                key={`${item.planet_name}-${i}`}
                className="cursor-pointer"
                onClick={() => setSelectedPlanet(item.planet_name)}
              >
                <TableCell className="font-data text-muted-foreground">
                  {i + 1}
                </TableCell>
                <TableCell className="font-medium">
                  <Link
                    to={`/planets/${encodeURIComponent(item.planet_name)}`}
                    className="text-foreground hover:text-chart-1 transition-colors"
                    onClick={e => e.stopPropagation()}
                  >
                    {item.planet_name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {item.hostname ?? '—'}
                </TableCell>
                <TableCell>
                  {item.detail ? (
                    <Badge variant="secondary" className="text-xs font-normal">{item.detail}</Badge>
                  ) : '—'}
                </TableCell>
                <TableCell className="text-right font-data text-chart-1">
                  {item.discovery_score != null ? item.discovery_score.toFixed(1) : '—'}
                </TableCell>
              </TableRow>
            ))}

            {rankings?.length === 0 && !isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  No entries in this category
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Sheet open={!!selectedPlanet} onOpenChange={() => setSelectedPlanet(null)}>
        <SheetContent className="overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{selectedPlanet}</SheetTitle>
            <SheetDescription>Planet details</SheetDescription>
          </SheetHeader>
          {selectedPlanet && <PlanetDetailPanel name={selectedPlanet} />}
        </SheetContent>
      </Sheet>
    </>
  )
}
