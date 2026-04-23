import { useEffect, useRef, useState } from 'react'
import type { CardMatch } from '../../types/api'
import { ManaSymbolRail } from './ManaSymbolRail'
import { SearchInput } from './SearchInput'
import { SearchSuggestions } from './SearchSuggestions'
import { useCardAutocompleteQuery } from './useCardAutocompleteQuery'

const SEARCH_SUGGESTIONS_ID = 'search-suggestions-listbox'

interface SearchBoxProps {
  className?: string
  value: string
  onChange: (value: string) => void
  onSubmit: (submittedValue?: string) => void
  onCardSelect?: (card: CardMatch) => void
  autoFocus?: boolean
  showManaRail?: boolean
  variant?: 'home' | 'topbar'
}

export function SearchBox({
  className,
  value,
  onChange,
  onSubmit,
  onCardSelect,
  autoFocus = false,
  showManaRail = true,
  variant = 'home',
}: SearchBoxProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [pendingInsert, setPendingInsert] = useState<{ id: number; symbol: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const blurFrameRef = useRef<number | null>(null)
  const internalPointerActiveRef = useRef(false)

  const autocomplete = useCardAutocompleteQuery(value)
  const suggestions: CardMatch[] = autocomplete.data ?? []
  const isLoading = autocomplete.isFetching

  // activeIndex is clamped at render time against the live suggestions list.
  // If the list shrinks under the hovered index it just snaps back to -1; any
  // concrete reset to -1 happens in the onChange handler instead of a
  // setState-in-effect.
  const effectiveActiveIndex = activeIndex >= suggestions.length ? -1 : activeIndex

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

  const handleInputChange = (next: string) => {
    onChange(next)
    setActiveIndex(-1)
    if (!isFocused) return
    // Open the panel as soon as the query is long enough to suggest, close it
    // otherwise. Kept in the event handler so the state flip is user-driven,
    // not an effect that reacts to changing props.
    setIsOpen(next.trim().length >= 2)
  }

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
    if (card.oracle_id && onCardSelect) {
      onCardSelect(card)
    } else {
      onSubmit(card.name)
    }
  }

  const handleArrowNavigate = (direction: 'up' | 'down') => {
    if (suggestions.length === 0) return

    setActiveIndex((current) => {
      const clamped = current >= suggestions.length ? -1 : current
      if (direction === 'down') {
        return clamped < 0 ? 0 : Math.min(clamped + 1, suggestions.length - 1)
      }

      if (clamped <= 0) return 0
      return clamped - 1
    })
  }

  const handleSubmit = () => {
    if (effectiveActiveIndex >= 0 && suggestions[effectiveActiveIndex]) {
      handleSelect(suggestions[effectiveActiveIndex])
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
        activeIndex={effectiveActiveIndex}
        suggestionsId={SEARCH_SUGGESTIONS_ID}
        suggestionsOpen={isOpen && suggestions.length > 0}
        pendingInsert={pendingInsert}
        onChange={handleInputChange}
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
          id={SEARCH_SUGGESTIONS_ID}
          variant={variant}
          items={suggestions}
          activeIndex={effectiveActiveIndex}
          isLoading={isLoading}
          onSelect={handleSelect}
          onHover={setActiveIndex}
        />
      ) : null}
    </div>
  )
}
