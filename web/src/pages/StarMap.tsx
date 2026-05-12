import { useEffect, useRef, useState, useCallback } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { AnimatePresence } from 'framer-motion'
import { useStarPositions, useStarSystem } from '@/hooks/useApi'
import { teffToRGB } from '@/lib/astro'
import {
  vertexShader, fragmentShader, teffToSize,
  addGalaxyBackground, addSunMarker,
  type OrbitingPlanet, type ViewMode,
} from '@/lib/starmap-helpers'
import type { StarPositionItem } from '@/types'

import '@fontsource/dm-mono/400.css'
import '@fontsource/dm-mono/500.css'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'

import StarMapTooltip from '@/components/starmap/StarMapTooltip'
import StarMapSearch from '@/components/starmap/StarMapSearch'
import StarMapPanel from '@/components/starmap/StarMapPanel'
import StarMapHUD from '@/components/starmap/StarMapHUD'

const SCALE = 0.15

export default function StarMap() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { data } = useStarPositions()
  const [selected, setSelected] = useState<StarPositionItem | null>(null)
  const [hovered, setHovered] = useState<{ star: StarPositionItem; x: number; y: number } | null>(null)
  const [systemViewId, setSystemViewId] = useState<string | null>(null)
  const [canvasReady, setCanvasReady] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('galaxy')
  const { data: systemData } = useStarSystem(systemViewId)
  const starsDataRef = useRef<StarPositionItem[]>([])
  const [planetLabels, setPlanetLabels] = useState<{ name: string; x: number; y: number }[]>([])
  const labelFrameRef = useRef(0)

  // Refs for both scenes
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const galaxyRef = useRef<{
    scene: THREE.Scene; camera: THREE.PerspectiveCamera
    controls: OrbitControls; starPoints: THREE.Points
    starMat: THREE.ShaderMaterial; sunMarker: THREE.Mesh
  } | null>(null)
  const systemRef = useRef<{
    scene: THREE.Scene; camera: THREE.PerspectiveCamera
    controls: OrbitControls; planets: OrbitingPlanet[]
  } | null>(null)
  const frameRef = useRef<number>(0)
  const viewModeRef = useRef<ViewMode>('galaxy')

  /* ── Switch to system view ─────────────────────────────────────── */
  const handleStarClick = useCallback((star: StarPositionItem) => {
    setSelected(star)
    setSystemViewId(star.id)
    setViewMode('system')
    viewModeRef.current = 'system'
    setHovered(null)
    // Disable galaxy controls
    if (galaxyRef.current) galaxyRef.current.controls.enabled = false
    // Enable system controls
    if (systemRef.current) systemRef.current.controls.enabled = true
  }, [])

  /* ── Switch back to galaxy ─────────────────────────────────────── */
  const closeSystem = useCallback(() => {
    setSelected(null)
    setSystemViewId(null)
    setViewMode('galaxy')
    viewModeRef.current = 'galaxy'
    setPlanetLabels([])
    if (galaxyRef.current) {
      galaxyRef.current.controls.enabled = true
      galaxyRef.current.controls.autoRotate = true
    }
    if (systemRef.current) systemRef.current.controls.enabled = false
  }, [])

  /* ── Build system scene when data arrives ──────────────────────── */
  useEffect(() => {
    if (!systemData || !rendererRef.current) return

    // Dispose old system scene if exists
    if (systemRef.current) {
      systemRef.current.controls.dispose()
      systemRef.current.scene.traverse(obj => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry.dispose()
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
    }

    const scene = new THREE.Scene()
    const el = containerRef.current!
    const camera = new THREE.PerspectiveCamera(55, el.clientWidth / el.clientHeight, 0.01, 5000)

    const controls = new OrbitControls(camera, rendererRef.current.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.06
    controls.rotateSpeed = 0.5
    controls.zoomSpeed = 0.8
    controls.minDistance = 1
    controls.maxDistance = 1500
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.15

    // ── PROBLEM 3 FIX: Star field background ──
    const createStarField = () => {
      const positions = new Float32Array(3000 * 3)
      const colors = new Float32Array(3000 * 3)
      const palette = [
        [0.95, 0.97, 1.00], [1.00, 1.00, 0.98], [1.00, 0.98, 0.88],
        [1.00, 0.95, 0.75], [1.00, 0.85, 0.55], [1.00, 0.72, 0.45],
      ]
      for (let i = 0; i < 3000; i++) {
        const theta = Math.random() * Math.PI * 2
        const phi = Math.acos(2 * Math.random() - 1)
        const r = 600 + Math.random() * 400
        positions[i*3]   = r * Math.sin(phi) * Math.cos(theta)
        positions[i*3+1] = r * Math.sin(phi) * Math.sin(theta)
        positions[i*3+2] = r * Math.cos(phi)
        const c = Math.random() < 0.6
          ? palette[2]
          : palette[Math.floor(Math.random() * palette.length)]
        colors[i*3] = c[0]; colors[i*3+1] = c[1]; colors[i*3+2] = c[2]
      }
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      return new THREE.Points(geo, new THREE.PointsMaterial({
        size: 1.0, vertexColors: true, sizeAttenuation: true,
        transparent: true, opacity: 0.85,
      }))
    }
    scene.add(createStarField())

    // Ambient + hemisphere light for visible planets
    scene.add(new THREE.AmbientLight(0x334466, 0.8))
    scene.add(new THREE.HemisphereLight(0xffffff, 0x222244, 0.4))

    // ── PROBLEM 1 FIX: Star color from blackbody ──
    const STAR_SCALE = 0.8
    const teff = systemData.teff || 5778
    const rgb = teffToRGB(teff)
    const starColor = new THREE.Color(rgb[0], rgb[1], rgb[2])
    console.log(`Star teff=${teff} → rgb(${Math.round(rgb[0]*255)},${Math.round(rgb[1]*255)},${Math.round(rgb[2]*255)})`)

    // ── SCALING FIX: Star radius ──
    const starSceneRadius = (systemData.radius_solar ?? 1.0) * STAR_SCALE

    // Host star at origin — color from blackbody
    const starGeo = new THREE.SphereGeometry(starSceneRadius, 64, 64)
    const starMat = new THREE.MeshBasicMaterial({ color: starColor })
    const starMesh = new THREE.Mesh(starGeo, starMat)
    scene.add(starMesh)

    // ── PROBLEM 2 FIX: THREE layers of glow ──
    const createGlowTexture = (): THREE.CanvasTexture => {
      const canvas = document.createElement('canvas')
      canvas.width = 256; canvas.height = 256
      const ctx = canvas.getContext('2d')!
      const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 128)
      gradient.addColorStop(0, 'rgba(255,255,255,1)')
      gradient.addColorStop(0.2, 'rgba(255,255,255,0.6)')
      gradient.addColorStop(0.5, 'rgba(255,255,255,0.15)')
      gradient.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, 256, 256)
      return new THREE.CanvasTexture(canvas)
    }
    const glowTex = createGlowTexture()

    // Layer 1 — Large corona bloom
    const glow1 = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: starColor, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.8,
    }))
    glow1.scale.set(starSceneRadius * 8, starSceneRadius * 8, 1)
    scene.add(glow1)

    // Layer 2 — Medium inner glow
    const glow2 = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: starColor, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.5,
    }))
    glow2.scale.set(starSceneRadius * 4, starSceneRadius * 4, 1)
    scene.add(glow2)

    // Layer 3 — Tight halo
    const glow3 = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: starColor, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.9,
    }))
    glow3.scale.set(starSceneRadius * 2, starSceneRadius * 2, 1)
    scene.add(glow3)

    // Point light — color matches blackbody
    const light = new THREE.PointLight(starColor, 4, 500, 1.5)
    scene.add(light)

    // ── Habitable zone ring ──
    const lum = systemData.radius_solar
      ? Math.pow(systemData.radius_solar, 2) * Math.pow(teff / 5778, 4) : 1
    const hzInnerAU = Math.sqrt(lum / 1.1)
    const hzOuterAU = Math.sqrt(lum / 0.53)
    const hzInner = Math.max(starSceneRadius * 3, Math.pow(hzInnerAU, 0.5) * 15)
    const hzOuter = Math.max(starSceneRadius * 3, Math.pow(hzOuterAU, 0.5) * 15)
    const hzGeo = new THREE.RingGeometry(hzInner, hzOuter, 128)
    const hzMat = new THREE.MeshBasicMaterial({
      color: 0x2dd4bf, transparent: true, opacity: 0.12,
      side: THREE.DoubleSide, depthWrite: false,
    })
    const hz = new THREE.Mesh(hzGeo, hzMat)
    hz.rotation.x = -Math.PI * 0.5
    scene.add(hz)

    // ── Planets with elliptical orbits + correct scaling ──
    let maxOrbitR = starSceneRadius * 6
    const planets: OrbitingPlanet[] = []

    systemData.planets.forEach((p, i) => {
      const sma = p.semi_major_axis_au
      if (!sma) return

      // SCALING FIX: orbit distance — sqrt scale so close-in planets clear the star
      // and far-out planets don't push camera to infinity
      const ORBIT_SCALE = 15
      const orbR = Math.max(starSceneRadius * 3, Math.pow(sma, 0.5) * ORBIT_SCALE)
      if (orbR > maxOrbitR) maxOrbitR = orbR

      // Eccentricity for elliptical orbit
      const ecc = Math.min(0.9, p.eccentricity || 0)
      const semiMinor = orbR * Math.sqrt(1 - ecc * ecc)
      const focusOffset = orbR * ecc

      // Elliptical orbit path
      const curve = new THREE.EllipseCurve(
        -focusOffset, 0, orbR, semiMinor,
        0, 2 * Math.PI, false, 0
      )
      const orbitPoints = curve.getPoints(256)
      const orbitGeo = new THREE.BufferGeometry().setFromPoints(
        orbitPoints.map(pt => new THREE.Vector3(pt.x, 0, pt.y))
      )
      scene.add(new THREE.Line(orbitGeo, new THREE.LineBasicMaterial({
        color: 0x8899aa, transparent: true, opacity: 0.4,
      })))

      // SCALING FIX: planet radius — pl_rade is Earth radii, 109 R⊕ = 1 R☉
      let planetSceneRadius = (p.radius_earth || 1.0) / 109.0 * STAR_SCALE
      planetSceneRadius = Math.max(planetSceneRadius, starSceneRadius * 0.04) // min visible
      planetSceneRadius = Math.min(planetSceneRadius, starSceneRadius * 1.5)  // safety clamp
      console.log(`${p.planet_name}: r_earth=${p.radius_earth}, scene_r=${planetSceneRadius.toFixed(4)}, star_r=${starSceneRadius.toFixed(4)}`)

      const isRocky = (p.radius_earth || 1) < 2
      let pColor: number
      if (p.composite_score && p.composite_score > 0.5) {
        pColor = 0x5588cc
      } else if (isRocky) {
        pColor = [0xcc7744, 0xaa6633, 0x887766, 0xbb8855][i % 4]
      } else {
        pColor = [0xccaa66, 0xddbb77, 0xbbaa55, 0xeedd88][i % 4]
      }
      const pGeo = new THREE.SphereGeometry(planetSceneRadius, 32, 32)
      const pMat = new THREE.MeshStandardMaterial({
        color: pColor, roughness: 0.7, metalness: 0.1,
        emissive: new THREE.Color(pColor).multiplyScalar(0.15),
      })
      const pMesh = new THREE.Mesh(pGeo, pMat)
      const fixedAngle = (i * 2.39996) % (Math.PI * 2)
      const rx = orbR * Math.cos(fixedAngle) - focusOffset
      const rz = semiMinor * Math.sin(fixedAngle)
      pMesh.position.set(rx, 0, rz)
      scene.add(pMesh)

      planets.push({
        mesh: pMesh, name: p.planet_name,
        orbitRadius: orbR, speed: 0, angle: fixedAngle,
      })
    })

    // Camera framing — pull way back to see entire system (NASA-like)
    const camDist = Math.max(maxOrbitR * 3.5, 30)
    camera.position.set(camDist * 0.3, camDist * 0.6, camDist * 0.7)
    controls.target.set(0, 0, 0)
    controls.update()

    systemRef.current = { scene, camera, controls, planets }
  }, [systemData])

  /* ── Main renderer + galaxy scene setup ────────────────────────── */
  useEffect(() => {
    const el = containerRef.current
    if (!el || !data?.stars?.length) return

    const stars = data.stars
    starsDataRef.current = stars
    const count = stars.length

    // ── Renderer (shared) ──
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' })
    renderer.setSize(el.clientWidth, el.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x05050a, 1)
    el.appendChild(renderer.domElement)
    renderer.domElement.style.cursor = 'crosshair'
    rendererRef.current = renderer

    // ── Galaxy scene ──
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(60, el.clientWidth / el.clientHeight, 0.1, 12000)
    camera.position.set(0, 80, 300)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.06
    controls.rotateSpeed = 0.5
    controls.zoomSpeed = 0.8
    controls.minDistance = 5
    controls.maxDistance = 3000
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.08

    // Star points
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const hasPlanets = new Float32Array(count)
    stars.forEach((s, i) => {
      positions[i * 3] = s.x * SCALE
      positions[i * 3 + 1] = s.z * SCALE
      positions[i * 3 + 2] = s.y * SCALE
      const c = teffToRGB(s.teff)
      colors[i * 3] = c[0]; colors[i * 3 + 1] = c[1]; colors[i * 3 + 2] = c[2]
      sizes[i] = teffToSize(s.teff)
      hasPlanets[i] = s.n_planets > 0 ? 1.0 : 0.0
    })
    const starGeo = new THREE.BufferGeometry()
    starGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    starGeo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    starGeo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
    starGeo.setAttribute('aHasPlanets', new THREE.BufferAttribute(hasPlanets, 1))
    const starMat = new THREE.ShaderMaterial({
      vertexShader, fragmentShader,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: renderer.getPixelRatio() } },
      transparent: true, depthWrite: false, blending: THREE.NormalBlending,
    })
    const starPoints = new THREE.Points(starGeo, starMat)
    scene.add(starPoints)
    addGalaxyBackground(scene)
    const sunMarker = addSunMarker(scene)

    galaxyRef.current = { scene, camera, controls, starPoints, starMat, sunMarker }

    // ── Raycasting (galaxy only) ──
    const raycaster = new THREE.Raycaster()
    raycaster.params.Points = { threshold: 2 }
    const mouse = new THREE.Vector2()

    const setMouse = (e: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
    }

    const onPointerDown = (e: PointerEvent) => {
      if (viewModeRef.current !== 'galaxy') return
      setMouse(e)
      raycaster.setFromCamera(mouse, camera)
      const hits = raycaster.intersectObject(starPoints)
      if (hits.length > 0 && hits[0].index !== undefined) {
        const star = starsDataRef.current[hits[0].index]
        // Use the callback via ref to avoid stale closure
        starClickRef.current(star)
      }
    }

    const onPointerMove = (e: PointerEvent) => {
      if (viewModeRef.current !== 'galaxy') {
        renderer.domElement.style.cursor = 'grab'
        setHovered(null)
        return
      }
      setMouse(e)
      raycaster.setFromCamera(mouse, camera)
      const hits = raycaster.intersectObject(starPoints)
      if (hits.length > 0 && hits[0].index !== undefined) {
        setHovered({ star: starsDataRef.current[hits[0].index], x: e.clientX, y: e.clientY })
        renderer.domElement.style.cursor = 'pointer'
      } else {
        setHovered(null)
        renderer.domElement.style.cursor = 'crosshair'
      }
    }

    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    renderer.domElement.addEventListener('pointermove', onPointerMove)

    // ── Animation loop ──
    const clock = new THREE.Clock()
    let firstFrame = true

    const animate = () => {
      frameRef.current = requestAnimationFrame(animate)
      const dt = clock.getDelta()
      const t = clock.getElapsedTime()

      if (viewModeRef.current === 'galaxy' && galaxyRef.current) {
        const g = galaxyRef.current
        g.starMat.uniforms.uTime.value = t
        g.sunMarker.lookAt(g.camera.position)
        g.controls.update()
        renderer.render(g.scene, g.camera)
      } else if (viewModeRef.current === 'system' && systemRef.current) {
        const s = systemRef.current
        // No orbit animation — planets stay fixed
        // Slow planet self-rotation only
        s.planets.forEach(p => {
          p.mesh.rotation.y += dt * 0.3
        })
        s.controls.update()
        renderer.render(s.scene, s.camera)

        // Project planet positions to screen for HTML labels (~15fps)
        labelFrameRef.current++
        if (labelFrameRef.current % 4 === 0) {
          const labels = s.planets.map(p => {
            const pos = p.mesh.position.clone()
            pos.project(s.camera)
            return {
              name: p.name,
              x: (pos.x * 0.5 + 0.5) * el.clientWidth,
              y: (-pos.y * 0.5 + 0.5) * el.clientHeight,
            }
          })
          setPlanetLabels(labels)
        }
      }

      if (firstFrame) { firstFrame = false; setCanvasReady(true) }
    }
    animate()

    const onResize = () => {
      const w = el.clientWidth, h = el.clientHeight
      renderer.setSize(w, h)
      if (galaxyRef.current) {
        galaxyRef.current.camera.aspect = w / h
        galaxyRef.current.camera.updateProjectionMatrix()
      }
      if (systemRef.current) {
        systemRef.current.camera.aspect = w / h
        systemRef.current.camera.updateProjectionMatrix()
      }
    }
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('pointermove', onPointerMove)
      cancelAnimationFrame(frameRef.current)
      controls.dispose()
      renderer.dispose()
      starGeo.dispose()
      starMat.dispose()
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement)
    }
  }, [data])

  // Stable ref for handleStarClick so event handler doesn't go stale
  const starClickRef = useRef(handleStarClick)
  starClickRef.current = handleStarClick

  return (
    <>
      <div ref={containerRef} className="fixed inset-0" style={{ zIndex: 1 }} id="star-map-canvas" />

      <StarMapHUD starCount={data?.stars?.length} canvasReady={canvasReady} />

      {hovered && viewMode === 'galaxy' && (
        <StarMapTooltip star={hovered.star} x={hovered.x} y={hovered.y} />
      )}

      {viewMode === 'galaxy' && data?.stars && (
        <StarMapSearch stars={data.stars} onSelect={handleStarClick} />
      )}

      <AnimatePresence>
        {selected && viewMode === 'system' && (
          <StarMapPanel
            star={selected}
            systemData={systemData}
            onClose={closeSystem}
            viewMode={viewMode}
          />
        )}
      </AnimatePresence>

      {/* Planet labels — projected from 3D to screen */}
      {viewMode === 'system' && planetLabels.map(label => (
        <div
          key={label.name}
          className="fixed z-30 pointer-events-none"
          style={{
            left: label.x + 8,
            top: label.y - 6,
            fontFamily: 'var(--exo-font-mono)',
            fontSize: 11,
            color: '#dde1f0',
            letterSpacing: '0.04em',
            textShadow: '0 0 8px rgba(0,0,0,0.9), 0 0 2px rgba(0,0,0,1)',
            whiteSpace: 'nowrap',
          }}
        >
          {label.name}
        </div>
      ))}
    </>
  )
}
