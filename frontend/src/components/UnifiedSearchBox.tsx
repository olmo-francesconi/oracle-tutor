import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { MagnifyingGlassIcon } from '@phosphor-icons/react'
import { searchCards, searchOracleText } from '../api'
import type { CardMatch, SimilarCard } from '../types'
import { cn } from '../lib/cn'

interface UnifiedSearchBoxProps {
  className?: string
  autoFocus?: boolean
  initialValue?: string
  size?: 'default' | 'compact' | 'topBar'
  onDropdownChange?: (open: boolean) => void
}

export function UnifiedSearchBox({
  className,
  autoFocus,
  initialValue = '',
  size = 'default',
  onDropdownChange,
}: UnifiedSearchBoxProps) {
  const [query, setQuery] = useState(initialValue)
  const [nameMatches, setNameMatches] = useState<CardMatch[]>([])
  const [semanticMatches, setSemanticMatches] = useState<SimilarCard[]>([])
  const [isSemanticLoading, setIsSemanticLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const hasTyped = useRef(false)
  const navigate = useNavigate()
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Name search: 250ms debounce
  useEffect(() => {
    if (query.length < 2) {
      setNameMatches([])
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const results = await searchCards(query, 6, 0, controller.signal)
        if (!controller.signal.aborted) {
          setNameMatches(results)
          if (hasTyped.current) setIsOpen(true)
        }
      } catch {
        // silently ignore aborted requests
      }
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  // Semantic search: 600ms debounce
  useEffect(() => {
    if (query.length < 3) {
      setSemanticMatches([])
      setIsSemanticLoading(false)
      return
    }
    setIsSemanticLoading(true)
    const timer = setTimeout(async () => {
      try {
        const results = await searchOracleText(query, 0, 4)
        setSemanticMatches(results)
        if (hasTyped.current) setIsOpen(true)
      } catch {
        // silently ignore
      } finally {
        setIsSemanticLoading(false)
      }
    }, 600)
    return () => {
      clearTimeout(timer)
      setIsSemanticLoading(false)
    }
  }, [query])

  const handleNameSelect = (card: CardMatch) => {
    setIsOpen(false)
    const faceQuery = card.face_ix > 0 ? `?face=${card.face_ix}` : ''
    navigate(`/card/${card.oracle_id ?? ''}${faceQuery}`)
  }

  const handleSemanticSelect = (card: SimilarCard) => {
    setIsOpen(false)
    navigate(`/card/${card.oracle_id}`)
  }

  const handleSemanticSearch = () => {
    if (query.trim()) {
      setIsOpen(false)
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      const exact = nameMatches.find(
        (c) => c.name.toLowerCase() === query.trim().toLowerCase()
      )
      if (exact) {
        handleNameSelect(exact)
      } else {
        handleSemanticSearch()
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false)
    }
  }

  const hasDropdownContent =
    nameMatches.length > 0 || semanticMatches.length > 0 || isSemanticLoading
  const showDropdown = isOpen && hasDropdownContent && query.length >= 2

  useEffect(() => {
    onDropdownChange?.(showDropdown)
  }, [showDropdown, onDropdownChange])

  const displayQuery = query.length > 22 ? `${query.slice(0, 22)}…` : query
  const isCompact = size === 'compact'
  const isTopBar = size === 'topBar'
  const isSmall = isCompact || isTopBar

  return (
    <div ref={wrapperRef} className={cn('relative', className)}>
      {/* Input */}
      <div
        className={cn(
          'flex items-center gap-3',
          isTopBar
            ? 'h-full bg-[#F0EDE6] px-3'
            : cn(
                'border-2 border-[#111111] bg-white',
                isCompact ? 'px-3 py-[10px]' : 'px-4 py-[18px]'
              )
        )}
      >
        <MagnifyingGlassIcon
          className={cn(
            'shrink-0 text-[#111111]',
            isSmall ? 'h-4 w-4' : 'h-5 w-5'
          )}
          weight="bold"
        />
        <input
          type="text"
          value={query}
          onChange={(e) => { hasTyped.current = true; setQuery(e.target.value) }}
          onKeyDown={handleKeyDown}
          onFocus={() => hasDropdownContent && setIsOpen(true)}
          placeholder={
            isSmall
              ? 'search…'
              : 'search for a card or describe what it does…'
          }
          autoFocus={autoFocus}
          className={cn(
            'font-mono w-full bg-transparent text-[#111111] placeholder-[#ABABAB] outline-none',
            isSmall ? 'text-[13px]' : 'text-[15px]'
          )}
        />
      </div>

      {/* Dropdown */}
      {showDropdown && (
        <div
          className={cn(
            'absolute top-full z-[1000] flex flex-col border-2 border-t-0 border-[#111111] bg-white',
            isTopBar ? '-left-[2px] -right-[2px]' : 'left-0 right-0'
          )}
        >
          {/* Name section */}
          {nameMatches.length > 0 && (
            <>
              <div className="border-b border-[#E8E5DE] px-4 py-2">
                <span className="font-display text-[9px] font-bold tracking-[0.18em] text-[#7A7670] uppercase">
                  Cards
                </span>
              </div>
              {nameMatches.slice(0, 6).map((card) => (
                <button
                  key={`name-${card.oracle_id ?? card.name}-${card.face_ix}`}
                  onClick={() => handleNameSelect(card)}
                  className="font-mono flex w-full cursor-pointer items-center px-4 py-3 text-left text-[13px] text-[#111111] hover:bg-[#111111] hover:text-white"
                >
                  {card.name}
                </button>
              ))}
            </>
          )}

          {/* Yellow divider between sections */}
          {nameMatches.length > 0 &&
            (semanticMatches.length > 0 || isSemanticLoading) && (
              <div className="h-[2px] bg-[#F5C400]" />
            )}

          {/* Semantic section */}
          {(semanticMatches.length > 0 || isSemanticLoading) && (
            <>
              <div className="flex items-center justify-between border-b border-[#E8E5DE] px-4 py-2">
                <span className="font-display text-[9px] font-bold tracking-[0.18em] text-[#8B7A00] uppercase">
                  About &ldquo;{displayQuery}&rdquo;
                </span>
                {isSemanticLoading && (
                  <span className="font-mono text-[10px] text-[#ABABAB]">
                    searching…
                  </span>
                )}
              </div>
              {semanticMatches.slice(0, 4).map((card) => (
                <button
                  key={`semantic-${card.oracle_id}`}
                  onClick={() => handleSemanticSelect(card)}
                  className="font-mono flex w-full cursor-pointer items-center justify-between border-b border-[#F0EDE6] px-4 py-3 text-left text-[13px] text-[#111111] last:border-b-0 hover:bg-[#111111] hover:text-white"
                >
                  <span>{card.name}</span>
                  {card.type_line && (
                    <span className="ml-4 shrink-0 text-[11px] text-[#7A7670] hover:text-inherit">
                      {card.type_line.split('—')[0].trim()}
                    </span>
                  )}
                </button>
              ))}
            </>
          )}

          {/* See all results footer */}
          {(semanticMatches.length > 0 ||
            (nameMatches.length > 0 && !isSemanticLoading)) && (
            <>
              <div className="-mt-px h-[2px] bg-[#111111]" />
              <button
                onClick={handleSemanticSearch}
                className="font-display flex w-full cursor-pointer items-center justify-between px-4 py-3 text-[11px] font-bold tracking-[0.1em] text-[#111111] uppercase hover:bg-[#111111] hover:text-white"
              >
                <span>See all results for &ldquo;{displayQuery}&rdquo;</span>
                <span>→</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
