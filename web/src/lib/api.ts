const API_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'

async function fetchJson<T>(path: string, params?: Record<string, unknown>, init?: RequestInit): Promise<T> {
  const url = new URL(path, API_URL)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    })
  }
  const res = await fetch(url.toString(), init)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  stats: () => fetchJson<import('@/types').PlatformStats>('/api/stats'),

  priorityTarget: () => fetchJson<import('@/types').PriorityTarget>('/api/priority-target'),

  planets: (params: { page?: number; page_size?: number; method?: string; year_min?: number; year_max?: number; min_score?: number }) =>
    fetchJson<import('@/types').PaginatedResponse<import('@/types').PlanetListItem>>('/api/planets', params),

  planet: (name: string) => fetchJson<import('@/types').PlanetProfileVector>(`/api/planets/${encodeURIComponent(name)}`),

  spectrum: (name: string) => fetchJson<import('@/types').SpectrumView>(`/api/planets/${encodeURIComponent(name)}/spectrum`),

  stars: (params: { page?: number; page_size?: number }) =>
    fetchJson<import('@/types').PaginatedResponse<import('@/types').StarItem>>('/api/stars', params),

  starPositions: (limit = 6224) =>
    fetchJson<import('@/types').StarPositionsResponse>('/api/stars/positions', { limit }),

  starSystem: (starId: string) =>
    fetchJson<import('@/types').StarSystemResponse>(`/api/stars/${encodeURIComponent(starId)}/system`),

  rankings: (category: string, limit?: number) =>
    fetchJson<import('@/types').RankingItem[]>('/api/rankings', { category, limit }),

  alerts: (limit?: number) =>
    fetchJson<import('@/types').AlertItem[]>('/api/alerts', { limit }),

  startRetrieval: (planetName: string, specId: string) =>
    fetchJson<any>(`/api/planets/${encodeURIComponent(planetName)}/spectra/${encodeURIComponent(specId)}/retrieve`, undefined, { method: 'POST' }),

  getRetrievals: (planetName: string, specId: string) =>
    fetchJson<any[]>(`/api/planets/${encodeURIComponent(planetName)}/spectra/${encodeURIComponent(specId)}/retrievals`),

  getPosterior: (retrievalId: string) =>
    fetchJson<any>(`/api/retrievals/${encodeURIComponent(retrievalId)}/posterior`),

  validationMetrics: () =>
    fetchJson<any>('/api/validation/metrics'),
}
