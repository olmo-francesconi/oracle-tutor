import { useEffect, useRef, useState } from 'react'
import { searchCards } from '../../lib/api'
import type { CardMatch } from '../../types/api'
import { ManaSymbolRail } from './ManaSymbolRail'
import { SearchInput } from './SearchInput'
import { SearchSuggestions } from './SearchSuggestions'

interface SearchBoxProps {
  className?: string
  value: string
  onChange: (value: string) => void
  onSubmit: (submittedValue?: string) => void
  autoFocus?: boolean
  showManaRail?: boolean
  variant?: 'home' | 'topbar'
}

export function SearchBox({
  className,
  value,
  onChange,
  onSubmit,
  autoFocus = false,
  showManaRail = true,
  variant = 'home',
}: SearchBoxProps) {
  const [suggestions, setSuggestions] = useState<CardMatch[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [pendingInsert, setPendingInsert] = useState<{ id: number; symbol: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const blurFrameRef = useRef<number | null>(null)
  const internalPointerActiveRef = useRef(false)

  useEffect(() => {
    const trimmed = value.trim()
    if (trimmed.length < 2) {
      setSuggestions([])
      setIsLoading(false)
      setIsOpen(false)
      return
    }

    const controller = new AbortController()
    setIsOpen(isFocused)
    setIsLoading(true)

    const timer = window.setTimeout(async () => {
      try {
        const results = await searchCards(trimmed, 6, 0, controller.signal)
        if (!controller.signal.aborted) {
          setSuggestions(results)
          setIsOpen(isFocused)
        }
      } catch {
        if (!controller.signal.aborted) {
          setSuggestions([])
          setIsOpen(false)
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    }, 180)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
      setIsLoading(false)
    }
  }, [isFocused, value])

  useEffect(() => {
    setActiveIndex(-1)
  }, [value, suggestions.length])

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      setIsOpen(false)
      setIsFocused(false)
    }

    window.addEventListener('pointerdown', handlePointerDown)
    return () => window.removeEventListener('pointerdown', handlePointerDown)
  }, [])

  useEffect(() => {
    return () => {
      if (blurFrameRef.current !== null) {
        window.cancelAnimationFrame(blurFrameRef.current)
      }
    }
  }, [])

  const handleInsert = (symbol: string) => {
    setPendingInsert({
      id: Date.now(),
      symbol,
    })
    setIsOpen(true)
  }

  const handleSelect = (card: CardMatch) => {
    onChange(card.name)
    setIsOpen(false)
    onSubmit(card.name)
  }

  const handleArrowNavigate = (direction: 'up' | 'down') => {
    if (suggestions.length === 0) return

    setActiveIndex((current) => {
      if (direction === 'down') {
        return current < 0 ? 0 : Math.min(current + 1, suggestions.length - 1)
      }

      if (current <= 0) return 0
      return current - 1
    })
  }

  const handleSubmit = () => {
    if (activeIndex >= 0 && suggestions[activeIndex]) {
      handleSelect(suggestions[activeIndex])
      return
    }

    setIsOpen(false)
    onSubmit()
  }

  const rootClassName = [
    'relative grid w-full min-w-0 gap-0',
    variant === 'topbar' ? 'h-full self-stretch bg-transparent' : '',
    isOpen ? 'search-box-open' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      ref={rootRef}
      className={rootClassName}
      data-state={isOpen ? 'open' : 'closed'}
      onPointerDownCapture={() => {
        internalPointerActiveRef.current = true
      }}
      onPointerUpCapture={() => {
        window.requestAnimationFrame(() => {
          internalPointerActiveRef.current = false
        })
      }}
    >
      {showManaRail ? <ManaSymbolRail onInsert={handleInsert} transparentBackground={variant === 'home'} /> : null}

      <SearchInput
        value={value}
        autoFocus={autoFocus}
        variant={variant}
        pendingInsert={pendingInsert}
        onChange={onChange}
        onSubmit={handleSubmit}
        onArrowNavigate={handleArrowNavigate}
        onFocusChange={(focused) => {
          if (blurFrameRef.current !== null) {
            window.cancelAnimationFrame(blurFrameRef.current)
            blurFrameRef.current = null
          }

          setIsFocused(focused)

          if (!focused) {
            blurFrameRef.current = window.requestAnimationFrame(() => {
              blurFrameRef.current = null

              if (internalPointerActiveRef.current) {
                setIsFocused(true)
                return
              }

              if (rootRef.current?.contains(document.activeElement)) {
                setIsFocused(true)
                return
              }

              setIsFocused(false)
              setIsOpen(false)
            })
            return
          }

          if (value.trim().length >= 2) setIsOpen(true)
        }}
        onInsertHandled={() => setPendingInsert(null)}
      />

      {isOpen ? (
        <SearchSuggestions
          variant={variant}
          items={suggestions}
          activeIndex={activeIndex}
          isLoading={isLoading}
          onSelect={handleSelect}
          onHover={setActiveIndex}
        />
      ) : null}
    </div>
  )
}
