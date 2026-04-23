import { useEffect, useRef, useState } from 'react'

export type ViewportSize = {
  width: number
  height: number
}

const DEFAULT_VIEWPORT: ViewportSize = {
  width: 1280,
  height: 900,
}

function getViewportSize(): ViewportSize {
  if (typeof window === 'undefined') {
    return DEFAULT_VIEWPORT
  }

  return {
    width: Math.max(window.innerWidth, 0),
    height: Math.max(window.innerHeight, window.screen?.height ?? 0),
  }
}

export function useViewport(): ViewportSize {
  const [viewport, setViewport] = useState<ViewportSize>(getViewportSize)
  const resizeFrameRef = useRef<number | null>(null)

  useEffect(() => {
    const updateViewport = () => setViewport(getViewportSize())

    const scheduleUpdate = () => {
      if (resizeFrameRef.current !== null) return

      resizeFrameRef.current = window.requestAnimationFrame(() => {
        resizeFrameRef.current = null
        updateViewport()
      })
    }

    updateViewport()
    window.addEventListener('resize', scheduleUpdate)

    return () => {
      window.removeEventListener('resize', scheduleUpdate)

      if (resizeFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeFrameRef.current)
      }
    }
  }, [])

  return viewport
}
