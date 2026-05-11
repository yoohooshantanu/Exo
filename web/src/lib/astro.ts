/** Tanner Helland blackbody approximation — teff in Kelvin to [r, g, b] 0-1. */
export function teffToRGB(teff: number | null): [number, number, number] {
  if (!teff) return [0.7, 0.75, 0.85]
  const t = Math.max(1000, Math.min(40000, teff)) / 100
  let r: number, g: number, b: number

  if (t <= 66) {
    r = 1
    g = Math.max(0, Math.min(1, (99.47 * Math.log(t) - 161.12) / 255))
    b = t <= 19 ? 0 : Math.max(0, Math.min(1, (138.52 * Math.log(t - 10) - 305.04) / 255))
  } else {
    r = Math.max(0, Math.min(1, (329.7 * Math.pow(t - 60, -0.1332)) / 255))
    g = Math.max(0, Math.min(1, (288.12 * Math.pow(t - 60, -0.0755)) / 255))
    b = 1
  }

  const avg = (r + g + b) / 3
  const satBoost = teff < 4000 ? 0.25 : teff > 8000 ? 0.18 : 0.1
  r = Math.min(1, r + (r - avg) * satBoost)
  g = Math.min(1, g + (g - avg) * satBoost)
  b = Math.min(1, b + (b - avg) * satBoost)

  if (teff < 4000) { r = Math.min(1, r * 1.08); g = Math.max(0, g * 0.92) }
  if (teff > 8000) { b = Math.min(1, b * 1.06); r = Math.max(0, r * 0.94) }

  return [r, g, b]
}
