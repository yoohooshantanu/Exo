export interface PlanetListItem {
  planet_name: string
  hostname?: string
  discovery_method?: string
  discovery_year?: number
  radius_earth?: number
  mass_earth?: number
  period_days?: number
  eq_temperature_k?: number
  semi_major_axis_au?: number
  composite_score?: number
  composite_score_iqr?: number
  is_imputed?: boolean
  hz_score?: number
  cluster_name?: string
  discovery_score?: number
  observability_index?: number
  physical_triage_index?: number
  characterization_index?: number
}

export interface ProfileHabitability {
  composite_score?: number
  composite_score_iqr?: number
  is_imputed?: boolean
  similarity_score?: number
  hz_score?: number
  teq_score?: number
  radius_esi_score?: number
  mass_esi_score?: number
  eccentricity_score?: number
  age_score?: number
}

export interface ProfileBiosignatures {
  biosig_count: number
  molecules: string[]
  max_sigma?: number
}

export interface ProfileConfidence {
  has_spectra: boolean
  data_completeness: number
  instrument_best?: string
}

export interface ProfileAnomalyRisk {
  anomaly_count: number
  anomaly_types: string[]
  safety_score?: number
  xuv_escape_score?: number
  tidal_lock_score?: number
}

export interface ParamProvenance {
  status: 'measured' | 'derived' | 'imputed' | 'heuristic'
  source?: string
  uncertainty?: [number, number]
}

export interface DataProvenance {
  radius_earth?: ParamProvenance
  mass_earth?: ParamProvenance
  period_days?: ParamProvenance
  eq_temperature_k?: ParamProvenance
  semi_major_axis_au?: ParamProvenance
  eccentricity?: ParamProvenance
  composite_score?: ParamProvenance
}

export interface PlanetProfileVector {
  planet_name: string
  planet_id: string
  hostname?: string
  star_id?: string
  status: string
  discovery_method?: string
  discovery_year?: number
  radius_earth?: number
  mass_earth?: number
  period_days?: number
  eq_temperature_k?: number
  semi_major_axis_au?: number
  eccentricity?: number
  density_earth?: number
  cluster_label?: number
  cluster_name?: string
  distance_to_centroid?: number
  
  discovery_score: number
  observability_index?: number
  physical_triage_index?: number
  characterization_index?: number
  score_breakdown: ScoreBreakdown
  
  habitability: ProfileHabitability
  biosignatures: ProfileBiosignatures
  confidence: ProfileConfidence
  anomaly_risk: ProfileAnomalyRisk

  system_planets: SystemPlanetItem[]
  orbital_gaps: OrbitalGapItem[]

  data_provenance?: DataProvenance
}

export interface ScoreBreakdown {
  habitability: number
  biosignature: number
  data_quality: number
  orbital_context: number
  anomaly_penalty: number
  data_confidence?: number
}

export interface SystemPlanetItem {
  planet_name: string
  status: string
  semi_major_axis_au?: number
  period_days?: number
  mass_earth?: number
  radius_earth?: number
}

export interface OrbitalGapItem {
  predicted_period_days: number
  stability_confidence: number
  model_version: string
  mass_min_earth?: number
  mass_max_earth?: number
  detection_method_hint?: string
  isTarget?: boolean
}

export interface StarItem {
  star_id: string
  hip_name: string
  ra: number
  dec: number
  distance_pc?: number
  planet_count: number
}

export interface StarPositionItem {
  id: string
  hip_name: string
  x: number
  y: number
  z: number
  teff: number | null
  radius_solar: number | null
  distance_pc: number | null
  spectral_type: string | null
  n_planets: number
  hab_score_max: number
  has_prediction: boolean
  has_biosig: boolean
}

export interface StarPositionsResponse {
  stars: StarPositionItem[]
}

export interface PriorityTarget {
  planet_name: string
  hostname?: string
  discovery_score: number
  observability_index?: number
  physical_triage_index?: number
  characterization_index?: number
  hz_score?: number
  cluster_name?: string
  radius_earth?: number
  mass_earth?: number
  eq_temperature_k?: number
  biosig_count: number
  molecules_detected?: string
  anomaly_count: number
  rationale: string
}

export interface SpectrumPoint {
  wavelength_um: number
  depth_ppm?: number
  depth_err_upper?: number
  depth_err_lower?: number
}

export interface HitranLineItem {
  wavelength_um: number
  intensity?: number
  molecule: string
}

export interface MoleculeDetectionItem {
  molecule: string
  detection_sigma: number
  wavelength_um?: number
  hitran_match_count?: number
  abiotic_ruled_out?: boolean | null
  instrument?: string
  facility?: string
  method_notes?: string
}

export interface SpectrumView {
  spec_id: string
  instrument?: string
  facility?: string
  obs_type?: string
  points: SpectrumPoint[]
  detections: MoleculeDetectionItem[]
  hitran_lines: HitranLineItem[]
}

export interface RankingItem {
  planet_name: string
  hostname?: string
  discovery_score?: number
  observability_index?: number
  physical_triage_index?: number
  characterization_index?: number
  category: string
  detail?: string
}

export interface AlertItem {
  alert_type: string
  planet_name?: string
  hostname?: string
  detail: string
  score?: number
  severity: string
  created_at?: string
}

export interface PlatformStats {
  stars: number
  planets: number
  habitability_scores: number
  orbital_predictions: number
  molecule_detections: number
  atmospheric_spectra: number
  anomaly_flags: number
  taxonomy_clusters: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface SystemPlanet {
  planet_name: string
  radius_earth: number | null
  mass_earth: number | null
  semi_major_axis_au: number | null
  period_days: number | null
  eccentricity: number | null
  eq_temperature_k: number | null
  composite_score: number | null
  cluster_name: string | null
}

export interface StarSystemResponse {
  star_id: string
  hip_name: string
  ra: number | null
  dec: number | null
  distance_pc: number | null
  teff: number | null
  radius_solar: number | null
  mass_solar: number | null
  planets: SystemPlanet[]
}
