import { useEffect, useRef } from 'react'

export function CosmicStarfield() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animId: number
    let width = (canvas.width = window.innerWidth)
    let height = (canvas.height = window.innerHeight)

    const handleResize = () => {
      if (!canvas) return
      width = canvas.width = window.innerWidth
      height = canvas.height = window.innerHeight
    }
    window.addEventListener('resize', handleResize)

    // Generate stars
    const numStars = 120
    const stars = Array.from({ length: numStars }).map(() => ({
      x: Math.random() * width,
      y: Math.random() * height,
      size: Math.random() * 1.8 + 0.4,
      speed: Math.random() * 0.35 + 0.05,
      alpha: Math.random() * 0.8 + 0.2,
      pulse: Math.random() * 0.02 + 0.005,
      pulseDir: 1,
      color: Math.random() > 0.7 ? '#38bdf8' : Math.random() > 0.4 ? '#a855f7' : '#ffffff',
    }))

    // Floating dust or nebula particles
    const orbs = [
      { x: width * 0.2, y: height * 0.3, radius: 280, color: 'rgba(168, 85, 247, 0.05)' },
      { x: width * 0.8, y: height * 0.6, radius: 340, color: 'rgba(56, 189, 248, 0.04)' },
      { x: width * 0.5, y: height * 0.8, radius: 250, color: 'rgba(236, 72, 153, 0.03)' },
    ]

    const render = () => {
      ctx.clearRect(0, 0, width, height)

      // Draw subtle ambient glow orbs
      orbs.forEach((orb) => {
        const gradient = ctx.createRadialGradient(orb.x, orb.y, 10, orb.x, orb.y, orb.radius)
        gradient.addColorStop(0, orb.color)
        gradient.addColorStop(1, 'transparent')
        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(orb.x, orb.y, orb.radius, 0, Math.PI * 2)
        ctx.fill()
      })

      // Draw and animate twinkling stars
      stars.forEach((star) => {
        star.y -= star.speed
        if (star.y < 0) {
          star.y = height
          star.x = Math.random() * width
        }

        star.alpha += star.pulse * star.pulseDir
        if (star.alpha > 0.95) {
          star.alpha = 0.95
          star.pulseDir = -1
        } else if (star.alpha < 0.15) {
          star.alpha = 0.15
          star.pulseDir = 1
        }

        ctx.save()
        ctx.globalAlpha = star.alpha
        ctx.fillStyle = star.color
        ctx.shadowBlur = star.size > 1.2 ? 6 : 0
        ctx.shadowColor = star.color
        ctx.beginPath()
        ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      })

      animId = requestAnimationFrame(render)
    }

    render()

    return () => {
      window.removeEventListener('resize', handleResize)
      cancelAnimationFrame(animId)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0 opacity-80"
      aria-hidden="true"
    />
  )
}
