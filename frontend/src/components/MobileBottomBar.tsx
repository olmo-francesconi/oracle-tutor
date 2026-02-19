import { useEffect, useRef, useState } from 'react'
import { DeveloperLinks } from './DeveloperLinks'

export function MobileBottomBar() {
  const [keyboardOffset, setKeyboardOffset] = useState(0)
  const lastOffsetRef = useRef(0)
  const rafIdRef = useRef<number | null>(null)

  // Keep the fixed bar visible above the iOS keyboard by tracking VisualViewport.
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return

    const computeOffset = () => {
      const offsetTop = vv.offsetTop || 0
      // iOS/embedded webviews can report confusing viewport metrics when the keyboard opens.
      // Use the smaller of VisualViewport height and documentElement clientHeight as the
      // "actually visible" height.
      const docH = document.documentElement?.clientHeight || 0
      const visualH = vv.height || window.innerHeight
      const visibleH = docH > 0 ? Math.min(docH, visualH) : visualH

      // Position our fixed bar relative to the visual viewport bottom.
      return Math.max(0, window.innerHeight - visibleH - offsetTop)
    }

    const update = () => {
      const next = computeOffset()
      if (next === lastOffsetRef.current) return
      lastOffsetRef.current = next
      setKeyboardOffset(next)
    }

    const schedule = () => {
      if (rafIdRef.current != null) return
      rafIdRef.current = window.requestAnimationFrame(() => {
        rafIdRef.current = null
        update()
      })
    }

    // Initial measurement.
    update()

    vv.addEventListener('resize', schedule)
    vv.addEventListener('scroll', schedule)
    window.addEventListener('orientationchange', schedule)

    return () => {
      vv.removeEventListener('resize', schedule)
      vv.removeEventListener('scroll', schedule)
      window.removeEventListener('orientationchange', schedule)
      if (rafIdRef.current != null) {
        window.cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = null
      }
    }
  }, [])

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-40 md:hidden"
      style={{
        transform: keyboardOffset
          ? `translateY(-${keyboardOffset}px)`
          : undefined,
        transition: 'transform 150ms ease-out',
      }}
    >
      <div className="border-t border-white/10 bg-[#1c1c1c]/75 pb-[env(safe-area-inset-bottom)] backdrop-blur-md">
        <DeveloperLinks variant="light" split className="px-3 py-2" />
      </div>
    </div>
  )
}
