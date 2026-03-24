import { AnimatePresence, motion } from 'framer-motion'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { useNavigate } from 'react-router-dom'
import { OracleInput } from './OracleInput'
import { searchCards } from '../api'
import { cn } from '../lib/cn'
import type { CardMatch } from '../types'
import { getCardImageUrl } from '../utils'

// Simple pseudo-random generator based on string seed
const getRandomOffsets = (seed: string) => {
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = (hash << 5) - hash + seed.charCodeAt(i)
    hash |= 0
  }
  const rand = () => {
    hash = (hash * 1664525 + 1013904223) % 4294967296
    return (hash >>> 0) / 4294967296
  }

  return {
    x: (rand() - 0.5) * 20, // -10 to 10
    y: (rand() - 0.5) * 20, // -10 to 10
    r: (rand() - 0.5) * 2, // -1 to 1
  }
}

export function SearchCard() {
  const [nameQuery, setNameQuery] = useState('')
  const [oracleQuery, setOracleQuery] = useState('')
  const [suggestions, setSuggestions] = useState<CardMatch[]>([])
  const [focusedIndex, setFocusedIndex] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [isUIActive, setIsUIActive] = useState(false)
  const activityTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const swipeStartRef = useRef<{
    x: number
    y: number
    t: number
    pointerId: number
    active: boolean
  } | null>(null)
  const didSwipeRef = useRef(false)

  const navigate = useNavigate()
  const nameWrapperRef = useRef<HTMLDivElement>(null)
  const offsetsByIdRef = useRef<
    Map<string, ReturnType<typeof getRandomOffsets>>
  >(new Map())

  const getOffsets = useCallback((id: string) => {
    const existing = offsetsByIdRef.current.get(id)
    if (existing) return existing
    const next = getRandomOffsets(id)
    offsetsByIdRef.current.set(id, next)
    return next
  }, [])

  // Derived state for completion
  const bestMatch =
    suggestions.length > 0 &&
    focusedIndex >= 0 &&
    focusedIndex < suggestions.length
      ? suggestions[focusedIndex]
      : null

  const completion =
    bestMatch &&
    nameQuery &&
    bestMatch.name.toLowerCase().startsWith(nameQuery.toLowerCase())
      ? bestMatch.name.slice(nameQuery.length)
      : ''

  // Determine if we have any valid suggestions to show in stack
  const hasSuggestions = suggestions.length > 0
  const showSearch = !hasSuggestions || isUIActive

  const handleActivity = () => {
    setIsUIActive(true)
    if (activityTimeoutRef.current) clearTimeout(activityTimeoutRef.current)
    activityTimeoutRef.current = setTimeout(() => {
      setIsUIActive(false)
    }, 1400)
  }

  // Clear timeout on unmount
  useEffect(() => {
    return () => {
      if (activityTimeoutRef.current) clearTimeout(activityTimeoutRef.current)
    }
  }, [])

  // Prefetch a couple of upcoming images (idle to avoid competing with typing).
  useEffect(() => {
    const toPrefetch = suggestions.slice(focusedIndex, focusedIndex + 2)
    if (toPrefetch.length === 0) return
    if (document.visibilityState === 'hidden') return

    let cancelled = false
    const run = () => {
      if (cancelled) return
      for (const s of toPrefetch) {
        const url = getCardImageUrl(
          {
            id: s.id,
            name: s.name,
            image_side: s.image_side,
          },
          'small'
        )
        const img = new Image()
        img.decoding = 'async'
        img.loading = 'lazy'
        img.src = url
      }
    }

    const g = globalThis as {
      requestIdleCallback?: (
        cb: () => void,
        opts?: { timeout?: number }
      ) => number
      cancelIdleCallback?: (id: number) => void
    }
    const idle = g.requestIdleCallback
    const cancelIdle = g.cancelIdleCallback

    if (idle && cancelIdle) {
      const id = idle(run, { timeout: 1000 })
      return () => {
        cancelled = true
        cancelIdle(id)
      }
    }

    const t = setTimeout(run, 0)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [suggestions, focusedIndex])

  // Debounce for name search
  useEffect(() => {
    if (nameQuery.length < 2) {
      setSuggestions([])
      setFocusedIndex(0)
      setHasMore(false)
      return
    }

    const controller = new AbortController()

    const timer = setTimeout(async () => {
      try {
        const results = await searchCards(nameQuery, 10, 0, controller.signal)
        if (controller.signal.aborted) return
        setSuggestions(results)
        setFocusedIndex(0)
        setHasMore(results.length === 10)
      } catch (e) {
        if (!controller.signal.aborted) console.error(e)
      }
    }, 250)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [nameQuery])

  const fetchMoreSuggestions = useCallback(async () => {
    if (!hasMore || isLoadingMore) return

    setIsLoadingMore(true)
    try {
      const nextBatch = await searchCards(nameQuery, 10, suggestions.length)
      if (nextBatch.length < 10) {
        setHasMore(false)
      }

      if (nextBatch.length > 0) {
        setSuggestions((prev) => [...prev, ...nextBatch])
      }
    } catch (e) {
      console.error(e)
    } finally {
      setIsLoadingMore(false)
    }
  }, [hasMore, isLoadingMore, nameQuery, suggestions.length])

  const advanceFocusedIndex = useCallback(
    (delta: -1 | 1) => {
      if (suggestions.length === 0) return

      const nextIndex = focusedIndex + delta
      if (nextIndex < 0 || nextIndex >= suggestions.length) return

      setFocusedIndex(nextIndex)

      if (hasMore && !isLoadingMore && suggestions.length - nextIndex <= 5) {
        fetchMoreSuggestions()
      }
    },
    [
      fetchMoreSuggestions,
      focusedIndex,
      hasMore,
      isLoadingMore,
      suggestions.length,
    ]
  )

  // Desktop keyboard navigation for the card stack.
  // (Ignore keystrokes when an input/textarea is focused to avoid breaking typing/caret movement.)
  useEffect(() => {
    const isTextInputFocused = () => {
      const el = document.activeElement as HTMLElement | null
      if (!el) return false
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return true
      if (el.isContentEditable) return true
      return Boolean(el.closest('[contenteditable="true"], [role="textbox"]'))
    }

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.defaultPrevented) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (suggestions.length === 0) return
      if (showSearch && isTextInputFocused()) return

      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        advanceFocusedIndex(-1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        advanceFocusedIndex(1)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [suggestions.length, showSearch, advanceFocusedIndex])

  // When the UI fades out but the input is still focused, blur it so arrow-key navigation works.
  // Keep the input active even when the UI fades.

  const isInteractiveTarget = (target: EventTarget | null) => {
    const el = target as HTMLElement | null
    if (!el) return false
    return Boolean(
      el.closest(
        'input, textarea, button, a, [role="button"], [data-no-swipe="true"]'
      )
    )
  }

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!suggestions.length) return
    if (isInteractiveTarget(e.target)) return

    // Only react to primary touch/pen/mouse.
    if (e.isPrimary === false) return

    didSwipeRef.current = false

    // Ensure we still receive the pointer up even if it ends outside.
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      // no-op: not all browsers support pointer capture in all scenarios
    }

    swipeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      t: Date.now(),
      pointerId: e.pointerId,
      active: true,
    }
  }

  const handlePointerUpOrCancel = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = swipeStartRef.current
    if (!start?.active) return
    if (e.pointerId !== start.pointerId) return

    swipeStartRef.current = null

    // Ignore if the user interacted with inputs/buttons.
    if (isInteractiveTarget(e.target)) return

    const dt = Date.now() - start.t
    if (dt > 800) return

    const dx = e.clientX - start.x
    const dy = e.clientY - start.y

    const absX = Math.abs(dx)
    const absY = Math.abs(dy)

    // Swipe: require a mostly-horizontal gesture.
    if (absX >= 60 && absX >= absY * 1.2) {
      if (dx < 0) {
        didSwipeRef.current = true
        advanceFocusedIndex(1)
      } else {
        didSwipeRef.current = true
        advanceFocusedIndex(-1)
      }
      return
    }

    // Tap: treat a short, near-stationary pointer as "open top card".
    if (dt <= 500 && absX <= 10 && absY <= 10) {
      if (bestMatch) {
        handleNameSelect(bestMatch)
      }
    }
  }

  const handleNameSelect = (card: CardMatch) => {
    setNameQuery('')
    const faceQuery = card.face_ix > 0 ? `?face=${card.face_ix}` : ''
    navigate(`/card/${card.oracle_id ?? ''}${faceQuery}`)
  }

  const handleOracleSearch = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (oracleQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(oracleQuery.trim())}`)
    }
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleActivity()
    setNameQuery(e.target.value)
  }

  const handleNameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // Only wake the UI for text input edits (typed characters, backspace, delete).
    const isTextEditKey =
      (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.length === 1) ||
      e.key === 'Backspace' ||
      e.key === 'Delete'
    if (isTextEditKey) handleActivity()

    if (e.key === 'Tab' && !e.shiftKey && completion) {
      e.preventDefault()
      setNameQuery(nameQuery + completion)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return
      if (suggestions.length === 0) return

      // Always use left/right to navigate the suggested-images stack (even while
      // the textbox is visible/focused). Up/down are intentionally ignored below.
      e.preventDefault()
      advanceFocusedIndex(e.key === 'ArrowLeft' ? -1 : 1)
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      // Intentionally ignore up/down here.
      // (We don't want the suggested images stack to move with ArrowUp/ArrowDown.)
      return
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (bestMatch) {
        handleNameSelect(bestMatch)
      }
    }
  }

  return (
    <div
      className="relative aspect-[63/88] w-full max-w-[400px] rounded-[18px] bg-[#1c1c1c] shadow-2xl"
      onMouseMove={handleActivity}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUpOrCancel}
      onPointerCancel={handlePointerUpOrCancel}
      onMouseLeave={() => {
        if (activityTimeoutRef.current) clearTimeout(activityTimeoutRef.current)
        setIsUIActive(false)
      }}
      style={{ touchAction: suggestions.length ? 'pan-y' : 'auto' }}
    >
      {/* Card Stack */}
      <div
        className={cn(
          'absolute inset-0 overflow-visible rounded-[18px]',
          hasSuggestions && !showSearch ? 'z-20' : 'z-0'
        )}
      >
        <AnimatePresence initial={false}>
          {suggestions.slice(focusedIndex, focusedIndex + 5).map((card, i) => {
            const index = i // 0 is top
            const urlNormal = getCardImageUrl(
              {
                id: card.scryfall_id ?? '',
                name: card.name,
                image_side: card.image_side,
              },
              'normal'
            )
            const urlLarge = getCardImageUrl(
              {
                id: card.scryfall_id ?? '',
                name: card.name,
                image_side: card.image_side,
              },
              'large'
            )

            // Calculate random offsets based on card ID so they persist with the card
            const offsets = getOffsets(card.oracle_id ?? card.name)

            // Top card (index 0) should be centered and stable
            const isTop = index === 0
            const x = isTop ? 0 : index * 50 + offsets.x
            const y = isTop ? 0 : index * 5 + offsets.y
            const rotate = isTop ? 0 : index * 1.2 + offsets.r

            return (
              <motion.div
                key={`${card.oracle_id ?? card.name}:${card.face_ix}`}
                initial={
                  isTop
                    ? { opacity: 0 }
                    : { x: x + 20, opacity: 0, rotate: rotate + 2 }
                }
                animate={{
                  x,
                  y,
                  rotate,
                  scale: 1 - index * 0.02,
                  opacity: 1,
                  zIndex: 30 - index * 10,
                }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                className={cn(
                  'absolute top-0 left-0 h-full w-full origin-bottom-left rounded-[18px] shadow-xl',
                  isTop ? 'cursor-pointer' : ''
                )}
                style={{ pointerEvents: isTop ? 'auto' : 'none' }}
              >
                <img
                  src={urlNormal}
                  srcSet={`${urlNormal} 1x, ${urlLarge} 2x`}
                  sizes="400px"
                  alt={card.name}
                  loading="lazy"
                  decoding="async"
                  className="h-full w-full rounded-[18px] object-cover"
                />
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>

      {/* Content Container */}
      <div
        className={cn(
          'absolute inset-[16px] flex flex-col gap-[9px] rounded-[12px] px-[12px] py-[9px] transition-colors duration-500',
          !hasSuggestions ? 'bg-[#d1c8b8]' : 'bg-transparent',
          showSearch ? 'z-30' : 'z-10'
        )}
      >
        {/* Name Line (Search by Name) - Always visible on top */}
        <div
          className={cn(
            'relative z-20 mx-[1px] -mt-[1px] flex h-[34px] shrink-0 items-center transition-opacity duration-500 ease-in-out',
            showSearch ? 'opacity-100' : 'opacity-0'
          )}
          ref={nameWrapperRef}
        >
          <div
            className={cn(
              'relative flex h-full w-full items-center rounded-[4px] px-[8px] transition-all duration-300',
              hasSuggestions
                ? 'bg-gradient-to-r from-[#f1ece2]/85 from-55% to-transparent backdrop-blur-[1px]'
                : 'bg-transparent'
            )}
          >
            <input
              type="text"
              value={nameQuery}
              onChange={handleNameChange}
              onKeyDown={handleNameKeyDown}
              onFocus={handleActivity}
              placeholder="Search by card name..."
              className="relative z-10 w-full bg-transparent p-0 font-['Goudy_Bookletter_1911'] text-[16pt] font-bold text-[#1c1c1c] placeholder-[#737373] outline-none"
            />
          </div>
        </div>

        {/* Inner Elements Container */}
        <div className="relative z-10 flex flex-1 flex-col gap-[48px]">
          {/* Art Box (Placeholder) */}
          <div
            className={cn(
              'relative flex flex-1 items-center justify-center overflow-hidden rounded-[2px] border border-[#a89f91] bg-[#adaba5] shadow-inner transition-opacity duration-500',
              hasSuggestions ? 'opacity-0' : 'opacity-100'
            )}
          >
            <div className="absolute inset-0 bg-gradient-to-br from-[#e6e2d6] to-[#adaba5] opacity-50"></div>
          </div>

          {/* Text Box (Oracle Search) */}
          <OracleInput
            value={oracleQuery}
            onChange={setOracleQuery}
            onSearch={() => handleOracleSearch()}
            className={cn(
              'h-[38%] shrink-0',
              hasSuggestions ? 'pointer-events-none opacity-0' : 'opacity-100'
            )}
          />
        </div>
      </div>
    </div>
  )
}
