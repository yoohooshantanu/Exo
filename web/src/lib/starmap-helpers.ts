import * as THREE from 'three'

/* ── Design tokens ───────────────────────────────────────────────── */
export const T = {
  void:       '#05050a',
  base:       '#090912',
  raised:     '#0f0f1a',
  overlay:    '#16162a',
  borderSub:  '#141420',
  border:     '#1e1e30',
  borderHi:   '#2e2e50',
  text1:      '#dde1f0',
  text2:      '#5c6070',
  text3:      '#2e3040',
  textWhite:  '#f0f2ff',
  accent:     '#4f7fff',
  accentGlow: 'rgba(79,127,255,0.12)',
  accentDim:  '#0e1a33',
  green:      '#2e8b5a',
  greenDim:   '#091a10',
  amber:      '#c47a2a',
  amberDim:   '#1f1205',
  red:        '#8b2e2e',
  redDim:     '#1a0909',
}

/* ── Shaders for galaxy point cloud ──────────────────────────────── */

export const vertexShader = `
  uniform float uTime;
  uniform float uPixelRatio;
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aHasPlanets;
  varying vec3 vColor;
  varying float vHasPlanets;
  void main() {
    vColor = aColor;
    vHasPlanets = aHasPlanets;
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    float pulse = 1.0 + aHasPlanets * 0.08 * sin(uTime * 1.2 + position.x * 0.01);
    gl_PointSize = aSize * pulse * uPixelRatio * (80.0 / -mvPos.z);
    gl_PointSize = clamp(gl_PointSize, 0.5, 5.0);
    gl_Position = projectionMatrix * mvPos;
  }
`

export const fragmentShader = `
  varying vec3 vColor;
  varying float vHasPlanets;
  void main() {
    vec2 uv = gl_PointCoord - vec2(0.5);
    float d = dot(uv, uv);
    float intensity = exp(-8.0 * d);
    float core = exp(-20.0 * d);
    vec3 col = mix(vColor * 0.7, vColor * 1.4, core);
    float alpha = intensity * 0.9;
    if (alpha < 0.01) discard;
    gl_FragColor = vec4(col, alpha);
  }
`

/* ── Helpers ──────────────────────────────────────────────────────── */

export function teffToSize(teff: number | null): number {
  if (!teff) return 1.2
  const t = Math.max(2000, Math.min(40000, teff))
  return 0.8 + (t - 2000) / 38000 * 1.7
}

export function spectralClass(teff: number | null, spectralType: string | null): string {
  if (spectralType) return spectralType
  if (!teff) return '?'
  if (teff >= 30000) return 'O'
  if (teff >= 10000) return 'B'
  if (teff >= 7500) return 'A'
  if (teff >= 6000) return 'F'
  if (teff >= 5200) return 'G'
  if (teff >= 3700) return 'K'
  return 'M'
}

export function pcToLy(pc: number | null): string {
  if (!pc) return '—'
  return `${(pc * 3.26156).toFixed(0)}`
}

/* ── Orbit scaling for system view ───────────────────────────────── */

export function orbitScale(sma_au: number, starRadius: number): number {
  // Wide spacing: star is small, orbits are far out, like NASA's view
  return starRadius * 5 + Math.pow(sma_au, 0.4) * 40
}

/* ── Galaxy background (disk + halo) ─────────────────────────────── */

export function addGalaxyBackground(scene: THREE.Scene) {
  const diskLayers = [
    { count: 25000, radius: 5000, height: 80, size: 0.25, opacity: 0.32 },
    { count: 12000, radius: 3500, height: 50, size: 0.4, opacity: 0.26 },
    { count: 4000, radius: 1800, height: 30, size: 0.6, opacity: 0.22 },
  ]
  diskLayers.forEach(({ count, radius, height, size, opacity }) => {
    const pos = new Float32Array(count * 3)
    const cols = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2
      const t = Math.random()
      const r = radius * (0.15 + 0.85 * Math.pow(t, 0.6))
      const y = (Math.random() + Math.random() + Math.random() - 1.5) * (height / 1.5)
      pos[i * 3] = r * Math.cos(theta)
      pos[i * 3 + 1] = y
      pos[i * 3 + 2] = r * Math.sin(theta)
      const warmth = 0.7 + Math.random() * 0.3
      cols[i * 3] = warmth
      cols[i * 3 + 1] = warmth * (0.9 + Math.random() * 0.1)
      cols[i * 3 + 2] = warmth * (0.85 + Math.random() * 0.15)
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    geo.setAttribute('color', new THREE.BufferAttribute(cols, 3))
    scene.add(new THREE.Points(geo, new THREE.PointsMaterial({
      size, vertexColors: true, transparent: true, opacity, sizeAttenuation: true,
    })))
  })
  const haloCount = 8000
  const hPos = new Float32Array(haloCount * 3)
  const hCol = new Float32Array(haloCount * 3)
  for (let i = 0; i < haloCount; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    const r = 4500 * (0.5 + Math.random() * 0.5)
    hPos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
    hPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
    hPos[i * 3 + 2] = r * Math.cos(phi)
    const c = 0.55 + Math.random() * 0.25
    hCol[i * 3] = c
    hCol[i * 3 + 1] = c * 0.95
    hCol[i * 3 + 2] = c * 0.9
  }
  const hGeo = new THREE.BufferGeometry()
  hGeo.setAttribute('position', new THREE.BufferAttribute(hPos, 3))
  hGeo.setAttribute('color', new THREE.BufferAttribute(hCol, 3))
  scene.add(new THREE.Points(hGeo, new THREE.PointsMaterial({
    size: 0.35, vertexColors: true, transparent: true, opacity: 0.15, sizeAttenuation: true,
  })))
}

/* ── Sun marker ──────────────────────────────────────────────────── */

export function addSunMarker(scene: THREE.Scene) {
  const geo = new THREE.RingGeometry(0.6, 0.9, 16)
  const mat = new THREE.MeshBasicMaterial({
    color: 0xff6633, transparent: true, opacity: 0.8, side: THREE.DoubleSide,
  })
  const ring = new THREE.Mesh(geo, mat)
  ring.lookAt(new THREE.Vector3(0, 0, 1))
  scene.add(ring)
  return ring
}

/* ── Decorative background stars for system view ─────────────────── */

export function addSystemBackground(scene: THREE.Scene) {
  // Layer 1: dim distant field
  const addLayer = (count: number, rMin: number, rMax: number, sz: number, op: number) => {
    const pos = new Float32Array(count * 3)
    const cols = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      const r = rMin + Math.random() * (rMax - rMin)
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      pos[i * 3 + 2] = r * Math.cos(phi)
      // Warm color variation like real night sky
      const base = 0.5 + Math.random() * 0.5
      const warm = Math.random()
      cols[i * 3] = base * (0.9 + warm * 0.2)
      cols[i * 3 + 1] = base * (0.85 + warm * 0.15)
      cols[i * 3 + 2] = base * (0.8 + (1 - warm) * 0.3)
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    geo.setAttribute('color', new THREE.BufferAttribute(cols, 3))
    scene.add(new THREE.Points(geo, new THREE.PointsMaterial({
      size: sz, vertexColors: true, transparent: true, opacity: op, sizeAttenuation: true,
    })))
  }
  addLayer(4000, 600, 1500, 0.2, 0.5)  // dim field
  addLayer(1500, 500, 1200, 0.5, 0.6)  // mid brightness
  addLayer(300, 400, 1000, 0.9, 0.7)   // bright accent stars
}

/* ── Procedural star texture (equirectangular for sphere mapping) ── */

export function createStarTexture(rgb: [number, number, number], size = 512): THREE.CanvasTexture {
  // Equirectangular: width = 2x height for proper sphere UV mapping
  const w = size * 2, h = size
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d')!

  const r = Math.round(rgb[0] * 255)
  const g = Math.round(rgb[1] * 255)
  const b = Math.round(rgb[2] * 255)

  // Fill base color (bright, uniform like NASA's stars)
  ctx.fillStyle = `rgb(${r},${g},${b})`
  ctx.fillRect(0, 0, w, h)

  // Subtle limb darkening at poles (equirectangular latitude)
  const imageData = ctx.getImageData(0, 0, w, h)
  const d = imageData.data
  for (let py = 0; py < h; py++) {
    // Latitude: 0 at equator, 1 at poles
    const lat = Math.abs((py / h) - 0.5) * 2
    const limbFactor = 1.0 - lat * lat * 0.15 // subtle darkening at poles
    for (let px = 0; px < w; px++) {
      const i = (py * w + px) * 4
      // Add subtle granulation noise
      const noise = (Math.random() - 0.5) * 8
      d[i]     = Math.max(0, Math.min(255, d[i] * limbFactor + noise))
      d[i + 1] = Math.max(0, Math.min(255, d[i + 1] * limbFactor + noise * 0.8))
      d[i + 2] = Math.max(0, Math.min(255, d[i + 2] * limbFactor + noise * 0.6))
    }
  }
  ctx.putImageData(imageData, 0, 0)

  const tex = new THREE.CanvasTexture(canvas)
  tex.needsUpdate = true
  return tex
}

/* ── Procedural planet texture ───────────────────────────────────── */

export function createPlanetTexture(
  baseHue: number, // 0-360
  isRocky: boolean,
  size = 256
): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = size * 2; canvas.height = size // equirectangular
  const ctx = canvas.getContext('2d')!
  const w = canvas.width, h = canvas.height

  // Fill base color
  ctx.fillStyle = `hsl(${baseHue}, 25%, 30%)`
  ctx.fillRect(0, 0, w, h)

  // Simple value noise for terrain
  const noiseGrid = (cols: number, rows: number): number[][] => {
    const grid: number[][] = []
    for (let y = 0; y <= rows; y++) {
      grid[y] = []
      for (let x = 0; x <= cols; x++) {
        grid[y][x] = Math.random()
      }
    }
    return grid
  }

  const lerp = (a: number, b: number, t: number) => a + (b - a) * t
  const smooth = (t: number) => t * t * (3 - 2 * t)

  const sampleNoise = (grid: number[][], x: number, y: number, cols: number, rows: number): number => {
    const gx = (x / w) * cols, gy = (y / h) * rows
    const ix = Math.floor(gx) % (cols + 1), iy = Math.floor(gy) % (rows + 1)
    const fx = smooth(gx - Math.floor(gx)), fy = smooth(gy - Math.floor(gy))
    const nx = (ix + 1) % (cols + 1), ny = (iy + 1) % (rows + 1)
    return lerp(lerp(grid[iy][ix], grid[iy][nx], fx), lerp(grid[ny][ix], grid[ny][nx], fx), fy)
  }

  // Multi-octave noise
  const g1 = noiseGrid(8, 4), g2 = noiseGrid(16, 8), g3 = noiseGrid(32, 16)
  const imageData = ctx.getImageData(0, 0, w, h)
  const d = imageData.data

  for (let py = 0; py < h; py++) {
    for (let px = 0; px < w; px++) {
      const n = sampleNoise(g1, px, py, 8, 4) * 0.5 +
                sampleNoise(g2, px, py, 16, 8) * 0.3 +
                sampleNoise(g3, px, py, 32, 16) * 0.2
      const i = (py * w + px) * 4
      const variation = (n - 0.5) * (isRocky ? 80 : 40)
      d[i] = Math.max(0, Math.min(255, d[i] + variation))
      d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + variation * 0.8))
      d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + variation * 0.6))

      // Add bands for gas giants
      if (!isRocky) {
        const band = Math.sin(py / h * Math.PI * 12) * 15
        d[i] = Math.max(0, Math.min(255, d[i] + band))
        d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + band * 0.7))
      }
    }
  }
  ctx.putImageData(imageData, 0, 0)

  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = THREE.RepeatWrapping
  tex.needsUpdate = true
  return tex
}

/* ── Planet mesh tracking ────────────────────────────────────────── */

export interface OrbitingPlanet {
  mesh: THREE.Mesh
  name: string
  orbitRadius: number
  speed: number
  angle: number
}

export type ViewMode = 'galaxy' | 'system'
