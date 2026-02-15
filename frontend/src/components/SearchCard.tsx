import { MagnifyingGlass } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
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
    r: (rand() - 0.5) * 2   // -1 to 1
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

  // Derived state for completion
  const bestMatch = suggestions.length > 0 && focusedIndex >= 0 && focusedIndex < suggestions.length 
    ? suggestions[focusedIndex] 
    : null
  
  const completion =
    bestMatch &&
    nameQuery &&
    bestMatch.name.toLowerCase().startsWith(nameQuery.toLowerCase())
      ? bestMatch.name.slice(nameQuery.length)
      : ''

  const handleActivity = () => {
    setIsUIActive(true)
    if (activityTimeoutRef.current) clearTimeout(activityTimeoutRef.current)
    activityTimeoutRef.current = setTimeout(() => {
      setIsUIActive(false)
    }, 2000)
  }

  // Clear timeout on unmount
  useEffect(() => {
    return () => {
      if (activityTimeoutRef.current) clearTimeout(activityTimeoutRef.current)
    }
  }, [])

  // Prefetch next 5 images
  useEffect(() => {
    const toPrefetch = suggestions.slice(focusedIndex, focusedIndex + 5)
    toPrefetch.forEach(s => {
       const url = getCardImageUrl({ id: s.id, name: s.name } as any)
       const img = new Image()
       img.src = url
    })
  }, [suggestions, focusedIndex])

  // Debounce for name search
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (nameQuery.length >= 2) {
        try {
          const results = await searchCards(nameQuery, 10, 0)
          setSuggestions(results)
          setFocusedIndex(0)
          setHasMore(results.length === 10)
        } catch (e) {
          console.error(e)
        }
      } else {
        setSuggestions([])
        setFocusedIndex(0)
        setHasMore(false)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [nameQuery])

  const fetchMoreSuggestions = async () => {
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
  }

  const advanceFocusedIndex = (delta: -1 | 1) => {
    if (suggestions.length === 0) return

    const nextIndex = focusedIndex + delta
    if (nextIndex < 0 || nextIndex >= suggestions.length) return

    setFocusedIndex(nextIndex)

    if (hasMore && !isLoadingMore && suggestions.length - nextIndex <= 5) {
      fetchMoreSuggestions()
    }
  }

  const isInteractiveTarget = (target: EventTarget | null) => {
    const el = target as HTMLElement | null
    if (!el) return false
    return Boolean(el.closest('input, textarea, button, a, [role="button"], [data-no-swipe="true"]'))
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
      active: true
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
        handleNameSelect(bestMatch.id)
      }
    }
  }

  const handleNameSelect = (id: string) => {
    setNameQuery('')
    navigate(`/card/${id}`)
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
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') {
      handleActivity()
    }
    if (e.key === 'Tab' && !e.shiftKey && completion) {
      e.preventDefault()
      setNameQuery(nameQuery + completion)
    } else if (e.key === 'ArrowRight' && completion && e.currentTarget.selectionStart === nameQuery.length) {
      e.preventDefault()
      setNameQuery(nameQuery + completion)
    } else if (e.key === 'ArrowDown') {
      if (suggestions.length > 0) {
        e.preventDefault()
        
        const nextIndex = focusedIndex + 1
        if (nextIndex < suggestions.length) {
          setFocusedIndex(nextIndex)
        }
        
        if (hasMore && !isLoadingMore && suggestions.length - nextIndex <= 5) {
          fetchMoreSuggestions()
        }
      }
    } else if (e.key === 'ArrowUp') {
      if (suggestions.length > 0) {
        e.preventDefault()
        if (focusedIndex > 0) {
          setFocusedIndex((prev) => prev - 1)
        }
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (bestMatch) {
        handleNameSelect(bestMatch.id)
      }
    }
  }


  // Determine if we have any valid suggestions to show in stack
  const hasSuggestions = suggestions.length > 0
  const showSearch = !hasSuggestions || isUIActive

  return (
    <div 
      className="relative w-full max-w-[400px] aspect-[63/88] rounded-[18px] shadow-2xl bg-[#1c1c1c]"
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
          "absolute inset-0 overflow-visible rounded-[18px]",
          hasSuggestions && !showSearch ? "z-20" : "z-0"
        )}
      >
        <AnimatePresence initial={false}>
          {suggestions.slice(focusedIndex, focusedIndex + 5).map((card, i) => {
             const index = i // 0 is top
             const url = getCardImageUrl({ id: card.id, name: card.name } as any)
             
             // Calculate random offsets based on card ID so they persist with the card
             const offsets = getRandomOffsets(card.id)
             
             // Top card (index 0) should be centered and stable
             const isTop = index === 0
             const x = isTop ? 0 : index * 50 + offsets.x
             const y = isTop ? 0 : index * 5 + offsets.y
             const rotate = isTop ? 0 : index * 1.2 + offsets.r

             return (
               <motion.div
                 key={card.id}
                 initial={isTop ? { opacity: 0 } : { x: x + 20, opacity: 0, rotate: rotate + 2 }}
                 animate={{
                   x,
                   y,
                   rotate,
                   scale: 1 - index * 0.02,
                   opacity: 1,
                   zIndex: 30 - index * 10
                 }}
                 exit={{ opacity: 0 }}
                 transition={{ duration: 0.3 }}
                 className={cn(
                   "absolute top-0 left-0 h-full w-full rounded-[18px] shadow-xl origin-bottom-left",
                   isTop ? "cursor-pointer" : ""
                 )}
                 style={{ pointerEvents: isTop ? 'auto' : 'none' }}
               >
                 <img 
                   src={url} 
                   alt={card.name}
                   className="h-full w-full object-cover rounded-[18px]"
                 />
               </motion.div>
             )
          })}
        </AnimatePresence>
      </div>

      {/* Content Container */}
      <div className={cn(
          "absolute inset-[16px] flex flex-col gap-[9px] p-[9px] rounded-[12px] transition-colors duration-500",
          !hasSuggestions ? "bg-[#d1c8b8]" : "bg-transparent",
          showSearch ? "z-30" : "z-10"
      )}>
          
          {/* Name Line (Search by Name) - Always visible on top */}
          <div 
            className={cn(
              "relative h-[34px] z-20 shrink-0 flex items-center -mt-[1px] mx-[1px] transition-opacity duration-500",
              showSearch ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
            )} 
            ref={nameWrapperRef}
          >
            <div 
              className={cn(
                "relative h-full flex items-center rounded-[4px] px-[8px] shadow-sm transition-all duration-300",
                hasSuggestions 
                  ? "w-full bg-gradient-to-r from-[#e8e4d9] from-50% to-transparent" 
                  : "w-full bg-white/90 border border-[#a89f91]"
              )}
            >
              
              {/* Ghost Text Overlay */}
              <div className="pointer-events-none absolute inset-0 flex items-center px-[8px] font-bold text-[16px] md:text-[14px] font-['Goudy_Bookletter_1911']">
                <span className="opacity-0 whitespace-pre">{nameQuery}</span>
                <span className="text-[#a3a3a3] whitespace-pre">{completion}</span>
              </div>

              <input
                type="text"
                value={nameQuery}
                onChange={handleNameChange}
                onKeyDown={handleNameKeyDown}
                onFocus={handleActivity}
                placeholder="Search by card name..."
                className="relative z-10 w-full bg-transparent p-0 text-[16px] md:text-[14px] font-bold text-[#1c1c1c] placeholder-[#737373] outline-none font-['Goudy_Bookletter_1911']"
              />
              {!nameQuery && <MagnifyingGlass className="relative z-10 h-[16px] w-[16px] text-[#737373] shrink-0" />}
            </div>
          </div>

          {/* Inner Elements Container */}
          <div className="flex flex-col gap-[48px] flex-1 relative z-10">
              {/* Art Box (Placeholder) */}
              <div className={cn(
                  "relative flex-1 rounded-[2px] border border-[#a89f91] bg-[#adaba5] overflow-hidden shadow-inner flex items-center justify-center transition-opacity duration-500",
                  hasSuggestions ? "opacity-0" : "opacity-100"
              )}>
                  <div className="absolute inset-0 bg-gradient-to-br from-[#e6e2d6] to-[#adaba5] opacity-50"></div>
                  <div className="z-10 text-[#525252] font-serif italic text-center px-[16px]">
                      "Knowledge is power, and power is what we seek."
                  </div>
              </div>

              {/* Text Box (Oracle Search) */}
              <OracleInput
                value={oracleQuery}
                onChange={setOracleQuery}
                onSearch={() => handleOracleSearch()}
                className={cn(
                  "h-[38%] shrink-0",
                  hasSuggestions ? "opacity-0 pointer-events-none" : "opacity-100"
                )}
              />
          </div>

      </div>
    </div>
  )
}
