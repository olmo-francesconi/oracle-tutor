import { useEffect, useRef, useState } from 'react'
import { searchCards } from '../../lib/api'
import type { CardMatch } from '../../types/api'
import { ManaSymbolRail } from './ManaSymbolRail'
import { SearchInput } from './SearchInput'
import { SearchSuggestions } from './SearchSuggestions'

interface SearchBoxProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (submittedValue?: string) => void
  autoFocus?: boolean
}

function autoWrapManaSymbols(text: string): string {
  return text.replace(/(?<!\{)(W|U|B|R|G|C|S|X|Y|Z|T|Q|E|P)(?!\})/g, '{$1}')
}

export function SearchBox({
  value,
  onChange,
  onSubmit,
  autoFocus = false,
}: SearchBoxProps) {
  const [suggestions, setSuggestions] = useState<CardMatch[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const trimmed = value.trim()
    if (trimmed.length < 2) {
      setSuggestions([])
      setIsLoading(false)
      setIsOpen(false)
      return
    }

    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setIsLoading(true)

      try {
        const results = await searchCards(trimmed, 6, 0, controller.signal)
        if (!controller.signal.aborted) {
          setSuggestions(results)
          setIsOpen(true)
        }
      } catch {
        if (!controller.signal.aborted) {
          setSuggestions([])
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
  }, [value])

  useEffect(() => {
    setActiveIndex(-1)
  }, [value, suggestions.length])

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      setIsOpen(false)
    }

    window.addEventListener('pointerdown', handlePointerDown)
    return () => window.removeEventListener('pointerdown', handlePointerDown)
  }, [])

  const handleInsert = (symbol: string) => {
    const nextValue = value ? `${value}${symbol}` : symbol
    onChange(nextValue)
    setIsOpen(true)
  }

  const handleEditorChange = (nextValue: string) => {
    onChange(autoWrapManaSymbols(nextValue))
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

  return (
    <div ref={rootRef} className="search-box">
      <SearchInput
        value={value}
        autoFocus={autoFocus}
        onChange={handleEditorChange}
        onSubmit={handleSubmit}
        onArrowNavigate={handleArrowNavigate}
        onFocusChange={(focused) => {
          if (!focused) return
          if (value.trim()) setIsOpen(true)
        }}
      />

      <ManaSymbolRail onInsert={handleInsert} />

      {isOpen ? (
        <SearchSuggestions
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
