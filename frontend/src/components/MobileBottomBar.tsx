import { useEffect, useState } from 'react'
import { DeveloperLinks } from './DeveloperLinks'

export function MobileBottomBar() {
  const [keyboardOffset, setKeyboardOffset] = useState(0)

  // Keep the fixed bar visible above the iOS keyboard by tracking VisualViewport.
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return

    const update = () => {
      const offsetTop = vv.offsetTop || 0
      // iOS/embedded webviews can report confusing viewport metrics when the keyboard opens.
      // Use the smaller of VisualViewport height and documentElement clientHeight as the
      // "actually visible" height.
      const docH = document.documentElement?.clientHeight || 0
      const visualH = vv.height || window.innerHeight
      const visibleH = docH > 0 ? Math.min(docH, visualH) : visualH

      // Position our fixed bar relative to the visual viewport bottom.
      const offset = Math.max(0, window.innerHeight - visibleH - offsetTop)
      setKeyboardOffset(offset)
    }

    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    window.addEventListener('orientationchange', update)

    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
      window.removeEventListener('orientationchange', update)
    }
  }, [])

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-40 md:hidden"
      style={{
        transform: keyboardOffset ? `translateY(-${keyboardOffset}px)` : undefined,
        transition: 'transform 150ms ease-out',
      }}
    >
      <div className="border-t border-white/10 bg-[#1c1c1c]/75 backdrop-blur-md pb-[env(safe-area-inset-bottom)]">
        <DeveloperLinks
          variant="light"
          split
          className="px-3 py-2"
        />
      </div>
    </div>
  )
}

