import { X } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'framer-motion'
import { type ReactNode, useEffect } from 'react'
import { createPortal } from 'react-dom'

interface MobileDrawerProps {
  isOpen: boolean
  title?: string
  onClose: () => void
  children: ReactNode
}

export function MobileDrawer({
  isOpen,
  title,
  onClose,
  children,
}: MobileDrawerProps) {
  // Lock body scroll while open (matches CardOverlay pattern).
  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [isOpen])

  if (typeof document === 'undefined') return null

  return createPortal(
    <AnimatePresence>
      {isOpen ? (
        <motion.div
          className="fixed inset-0 z-[110] md:hidden"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Panel (near full-screen sheet; leaves a tappable backdrop margin) */}
          <motion.div className="pointer-events-none absolute inset-0 flex p-3">
            <motion.div
              className="pointer-events-auto flex h-full w-full flex-col overflow-hidden rounded-2xl bg-[#f5f2eb] text-[#1c1c1c] shadow-2xl ring-1 ring-black/10"
              initial={{ x: 24, opacity: 0.9 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 24, opacity: 0.9 }}
              transition={{ type: 'tween', duration: 0.2, ease: 'easeOut' }}
              role="dialog"
              aria-modal="true"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between border-b border-[#e5e5e5] px-4 py-3">
                <div className="text-sm font-semibold text-[#1c1c1c]">
                  {title ?? ''}
                </div>
                <button
                  onClick={onClose}
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-[#525252] transition-colors hover:bg-black/5 hover:text-[#1c1c1c]"
                  aria-label="Close"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4">{children}</div>
            </motion.div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body
  )
}
