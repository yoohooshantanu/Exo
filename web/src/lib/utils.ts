import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatAlertReason(type: string, detail?: string | null): string {
  const key = (detail || type || '').toLowerCase()
  
  if (['co2', 'co', 'ch4', 'nh3', 'h2o', 'o2', 'o3'].includes(key)) {
    return `Found trace of ${key.toUpperCase()} in atmosphere`
  }
  if (key === 'density_outlier') return 'Anomalous planetary density detected'
  if (key === 'temperature_outlier') return 'Anomalous equilibrium temperature detected'
  if (key === 'habitable_zone') return 'Planet orbits within the habitable zone'
  if (key === 'mass_outlier') return 'Anomalous planetary mass detected'
  if (key === 'radius_outlier') return 'Anomalous planetary radius detected'
  
  return detail || type || 'Critical pipeline anomaly detected'
}
