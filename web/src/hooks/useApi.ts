import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useStats() {
  return useQuery({ queryKey: ['stats'], queryFn: () => api.stats() })
}

export function usePriorityTarget() {
  return useQuery({ queryKey: ['priority-target'], queryFn: () => api.priorityTarget() })
}

export function usePlanets(params: { page?: number; page_size?: number; method?: string; year_min?: number; year_max?: number; min_score?: number }) {
  return useQuery({
    queryKey: ['planets', params],
    queryFn: () => api.planets(params),
  })
}

export function usePlanet(name: string) {
  return useQuery({
    queryKey: ['planet', name],
    queryFn: () => api.planet(name),
    enabled: !!name,
  })
}

export function useSpectrum(name: string) {
  return useQuery({
    queryKey: ['spectrum', name],
    queryFn: () => api.spectrum(name),
    enabled: !!name,
  })
}

export function useStars(params: { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ['stars', params],
    queryFn: () => api.stars(params),
  })
}

export function useStarPositions(limit = 6224) {
  return useQuery({
    queryKey: ['star-positions', limit],
    queryFn: () => api.starPositions(limit),
    staleTime: 1000 * 60 * 30, // Star positions are stable — 30 min cache
  })
}

export function useStarSystem(starId: string | null) {
  return useQuery({
    queryKey: ['star-system', starId],
    queryFn: () => api.starSystem(starId!),
    enabled: !!starId,
    staleTime: 1000 * 60 * 10,
  })
}

export function useRankings(category: string, limit = 50) {
  return useQuery({
    queryKey: ['rankings', category, limit],
    queryFn: () => api.rankings(category, limit),
  })
}

export function useAlerts(limit = 50) {
  return useQuery({
    queryKey: ['alerts', limit],
    queryFn: () => api.alerts(limit),
    refetchInterval: 30_000, // Poll every 30s for new alerts
  })
}

export function useRetrievals(planetName: string, specId: string) {
  return useQuery({
    queryKey: ['retrievals', planetName, specId],
    queryFn: () => api.getRetrievals(planetName, specId),
    enabled: !!planetName && !!specId,
    refetchInterval: (query) => {
      const data = query.state.data as any[]
      if (data?.some(r => r.status === 'running')) return 5000 // Poll every 5s if running
      return false
    }
  })
}

export function usePosterior(retrievalId: string | null) {
  return useQuery({
    queryKey: ['posterior', retrievalId],
    queryFn: () => api.getPosterior(retrievalId!),
    enabled: !!retrievalId,
  })
}
