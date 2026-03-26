import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CaretLeftIcon, CaretRightIcon, MagnifyingGlassIcon } from '@phosphor-icons/react'
import { searchCards, searchOracleText } from '../api'
import { getManaClass } from '../lib/manaSymbols'
import { SymbolText } from './SymbolText'
import type { CardMatch, SimilarCard } from '../types'
import { cn } from '../lib/cn'

interface UnifiedSearchBoxProps {
  className?: string
  autoFocus?: boolean
  initialValue?: string
  size?: 'default' | 'compact' | 'topBar' | 'hero'
  heroScale?: number
  onDropdownChange?: (open: boolean) => void
  onFocusChange?: (focused: boolean) => void
}

const SYMBOL_SCROLL_STEP = 240
const GENERIC_MANA_SYMBOLS = Array.from({ length: 21 }, (_, index) => `{${index}}`)
const LETTER_SYMBOLS = ['{X}', '{Y}', '{Z}'] as const
const HYBRID_MANA_SYMBOLS = [
  '{W/U}', '{U/B}', '{B/R}', '{R/G}', '{G/W}',
  '{W/B}', '{B/G}', '{G/U}', '{U/R}', '{R/W}',
] as const
const TWO_BRID_MANA_SYMBOLS = ['{2/W}', '{2/U}', '{2/B}', '{2/R}', '{2/G}'] as const
const PHYREXIAN_MANA_SYMBOLS = [
  '{P}', '{W/P}', '{U/P}', '{B/P}', '{R/P}', '{G/P}',
  '{W/U/P}', '{U/B/P}', '{B/R/P}', '{R/G/P}', '{G/W/P}',
] as const
const UTILITY_SYMBOLS = ['{E}', '{TK}', '{A}', '{PAW}'] as const
const SYMBOL_RAIL_ITEMS = [
  '{T}', '{Q}', '.',
  '{W}', '{U}', '{B}', '{R}', '{G}', '{C}', '{S}', '.',
  ...UTILITY_SYMBOLS, '.',
  ...HYBRID_MANA_SYMBOLS, '.',
  ...PHYREXIAN_MANA_SYMBOLS, '.',
  ...TWO_BRID_MANA_SYMBOLS, ...GENERIC_MANA_SYMBOLS, ...LETTER_SYMBOLS,
] as const
const HERO_MIN_HORIZONTAL_PADDING = 14
const HERO_MIN_VERTICAL_PADDING = 16
const HERO_MIN_TEXT_SIZE = 16
const HERO_MIN_ICON_SIZE = 18
const LONG_PLACEHOLDER = 'search for a card or describe what it does…'
const MEDIUM_PLACEHOLDER = 'search cards by meaning…'
const SHORT_PLACEHOLDER = 'search…'

type SelectionRange = {
  start: number
  end: number
}

function splitQueryParts(text: string) {
  return text.split(/(\{[^}]*\})/g).filter((part) => part.length > 0)
}

function getNodeRawLength(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent?.length ?? 0
  }

  if (node instanceof HTMLElement && node.dataset.token) {
    return node.dataset.token.length
  }

  return 0
}

function buildEditableContent(root: HTMLDivElement, text: string) {
  const fragment = document.createDocumentFragment()

  splitQueryParts(text).forEach((part) => {
    if (part.startsWith('{') && part.endsWith('}')) {
      const manaClass = getManaClass(part)
      if (manaClass) {
        const token = document.createElement('span')
        token.dataset.token = part
        token.contentEditable = 'false'
        token.className = 'inline-flex items-center align-middle'

        const icon = document.createElement('i')
        icon.className = `${manaClass} ms-cost align-[-0.08em]`
        icon.setAttribute('title', part)
        icon.setAttribute('aria-label', part)
        icon.style.fontSize = '0.9em'
        icon.style.verticalAlign = 'middle'

        token.appendChild(icon)
        fragment.appendChild(token)
        return
      }
    }

    fragment.appendChild(document.createTextNode(part))
  })

  root.replaceChildren(fragment)
}

function readRawQuery(root: HTMLDivElement): string {
  return Array.from(root.childNodes)
    .map((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent ?? ''
      }

      if (node instanceof HTMLElement && node.dataset.token) {
        return node.dataset.token
      }

      return ''
    })
    .join('')
}

function getRawOffset(root: HTMLDivElement, target: Node | null, offset: number): number {
  if (!target) return 0

  if (target === root) {
    return Array.from(root.childNodes)
      .slice(0, offset)
      .reduce((total, node) => total + getNodeRawLength(node), 0)
  }

  let total = 0
  for (const node of Array.from(root.childNodes)) {
    if (node === target) {
      if (node.nodeType === Node.TEXT_NODE) {
        return total + offset
      }

      if (node instanceof HTMLElement && node.dataset.token) {
        return total + (offset > 0 ? node.dataset.token.length : 0)
      }
    }

    if (node.contains(target)) {
      if (node.nodeType === Node.TEXT_NODE) {
        return total + offset
      }

      if (node instanceof HTMLElement && node.dataset.token) {
        return total + (offset > 0 ? node.dataset.token.length : 0)
      }
    }

    total += getNodeRawLength(node)
  }

  return total
}

function getSelectionRange(root: HTMLDivElement): SelectionRange {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) {
    const end = readRawQuery(root).length
    return { start: end, end }
  }

  const start = getRawOffset(root, selection.anchorNode, selection.anchorOffset)
  const end = getRawOffset(root, selection.focusNode, selection.focusOffset)

  return start <= end ? { start, end } : { start: end, end: start }
}

function setSelectionRange(root: HTMLDivElement, start: number, end: number) {
  const selection = window.getSelection()
  if (!selection) return

  const resolvePosition = (rawOffset: number) => {
    let total = 0
    const nodes = Array.from(root.childNodes)

    for (let index = 0; index < nodes.length; index += 1) {
      const node = nodes[index]
      const length = getNodeRawLength(node)

      if (node.nodeType === Node.TEXT_NODE && rawOffset <= total + length) {
        return { node, offset: rawOffset - total }
      }

      if (node instanceof HTMLElement && node.dataset.token) {
        if (rawOffset <= total) {
          return { node: root, offset: index }
        }

        if (rawOffset <= total + length) {
          return { node: root, offset: index + 1 }
        }
      }

      total += length
    }

    return { node: root, offset: nodes.length }
  }

  const range = document.createRange()
  const startPosition = resolvePosition(start)
  const endPosition = resolvePosition(end)

  range.setStart(startPosition.node, startPosition.offset)
  range.setEnd(endPosition.node, endPosition.offset)
  selection.removeAllRanges()
  selection.addRange(range)
}

export function UnifiedSearchBox({
  className,
  autoFocus,
  initialValue = '',
  size = 'default',
  heroScale = 1,
  onDropdownChange,
  onFocusChange,
}: UnifiedSearchBoxProps) {
  const [query, setQuery] = useState(initialValue)
  const [nameMatches, setNameMatches] = useState<CardMatch[]>([])
  const [semanticMatches, setSemanticMatches] = useState<SimilarCard[]>([])
  const [isSemanticLoading, setIsSemanticLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [canScrollSymbolsLeft, setCanScrollSymbolsLeft] = useState(false)
  const [canScrollSymbolsRight, setCanScrollSymbolsRight] = useState(false)
  const hasTyped = useRef(false)
  const initialCaretRef = useRef(initialValue.length)
  const navigate = useNavigate()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const symbolRailRef = useRef<HTMLDivElement>(null)
  const pendingSelectionRef = useRef<SelectionRange | null>(null)
  const textAreaRef = useRef<HTMLDivElement>(null)
  const placeholderMeasureRef = useRef<HTMLSpanElement>(null)
  const resizeFrameRef = useRef<number | null>(null)
  const [textAreaWidth, setTextAreaWidth] = useState(0)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false)
        setIsFocused(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!autoFocus || !editorRef.current) return
    editorRef.current.focus()
    setSelectionRange(editorRef.current, initialCaretRef.current, initialCaretRef.current)
  }, [autoFocus])

  useEffect(() => {
    const updateTextAreaWidth = () => {
      setTextAreaWidth(textAreaRef.current?.clientWidth ?? 0)
    }

    const scheduleUpdate = () => {
      if (resizeFrameRef.current !== null) return
      resizeFrameRef.current = window.requestAnimationFrame(() => {
        resizeFrameRef.current = null
        updateTextAreaWidth()
      })
    }

    updateTextAreaWidth()

    const observer = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(() => scheduleUpdate())
      : null

    if (textAreaRef.current && observer) {
      observer.observe(textAreaRef.current)
    }

    window.addEventListener('resize', scheduleUpdate)

    return () => {
      window.removeEventListener('resize', scheduleUpdate)
      observer?.disconnect()
      if (resizeFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeFrameRef.current)
      }
    }
  }, [])

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

  useEffect(() => {
    if (query.length < 3) {
      setSemanticMatches([])
      setIsSemanticLoading(false)
      return
    }

    setIsSemanticLoading(true)
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const results = await searchOracleText(query, 0, 4, undefined, controller.signal)
        if (!controller.signal.aborted) {
          setSemanticMatches(results.items)
          if (hasTyped.current) setIsOpen(true)
        }
      } catch {
        // silently ignore
      } finally {
        if (!controller.signal.aborted) {
          setIsSemanticLoading(false)
        }
      }
    }, 600)

    return () => {
      clearTimeout(timer)
      controller.abort()
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

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
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
      setIsFocused(false)
      editorRef.current?.blur()
    }
  }

  const focusEditorAt = (position: number) => {
    requestAnimationFrame(() => {
      if (!editorRef.current) return
      editorRef.current.focus()
      setSelectionRange(editorRef.current, position, position)
    })
  }

  const handleInsertSymbol = (symbol: string) => {
    const selection = editorRef.current
      ? getSelectionRange(editorRef.current)
      : { start: query.length, end: query.length }
    const nextQuery =
      query.slice(0, selection.start) + symbol + query.slice(selection.end)
    const nextCaret = selection.start + symbol.length

    hasTyped.current = true
    pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
    setQuery(nextQuery)
    setIsFocused(true)
    focusEditorAt(nextCaret)
  }

  const handleEditorInput = () => {
    if (!editorRef.current) return

    const nextQuery = readRawQuery(editorRef.current)
    const nextSelection = getSelectionRange(editorRef.current)

    hasTyped.current = true
    pendingSelectionRef.current = nextSelection
    setQuery(nextQuery)
  }

  const updateSymbolScrollState = () => {
    const rail = symbolRailRef.current
    if (!rail) {
      setCanScrollSymbolsLeft(false)
      setCanScrollSymbolsRight(false)
      return
    }

    const maxScrollLeft = rail.scrollWidth - rail.clientWidth
    setCanScrollSymbolsLeft(rail.scrollLeft > 4)
    setCanScrollSymbolsRight(rail.scrollLeft < maxScrollLeft - 4)
  }

  const scrollSymbols = (direction: 'left' | 'right') => {
    const rail = symbolRailRef.current
    if (!rail) return

    rail.scrollBy({
      left: direction === 'left' ? -SYMBOL_SCROLL_STEP : SYMBOL_SCROLL_STEP,
      behavior: 'smooth',
    })
  }

  const hasDropdownContent =
    nameMatches.length > 0 || semanticMatches.length > 0 || isSemanticLoading
  const showDropdown = isOpen && hasDropdownContent && query.length >= 2

  useEffect(() => {
    onDropdownChange?.(showDropdown)
  }, [showDropdown, onDropdownChange])

  useEffect(() => {
    onFocusChange?.(isFocused)
  }, [isFocused, onFocusChange])

  useEffect(() => {
    if (!isFocused) return

    updateSymbolScrollState()

    const rail = symbolRailRef.current
    if (!rail) return

    const handleScroll = () => updateSymbolScrollState()
    const handleResize = () => updateSymbolScrollState()

    rail.addEventListener('scroll', handleScroll)
    window.addEventListener('resize', handleResize)

    return () => {
      rail.removeEventListener('scroll', handleScroll)
      window.removeEventListener('resize', handleResize)
    }
  }, [isFocused])

  useLayoutEffect(() => {
    if (!editorRef.current) return

    buildEditableContent(editorRef.current, query)

    if (document.activeElement === editorRef.current) {
      const selection = pendingSelectionRef.current ?? {
        start: query.length,
        end: query.length,
      }
      setSelectionRange(editorRef.current, selection.start, selection.end)
    }
  }, [query])

  const displayQuery = query.length > 22 ? `${query.slice(0, 22)}…` : query
  const isCompact = size === 'compact'
  const isTopBar = size === 'topBar'
  const isHero = size === 'hero'
  const isSmall = isCompact || isTopBar
  const heroHorizontalPadding = Math.max(HERO_MIN_HORIZONTAL_PADDING, 16 * heroScale)
  const heroVerticalPadding = Math.max(HERO_MIN_VERTICAL_PADDING, 18 * heroScale)
  const heroTextSize = Math.max(HERO_MIN_TEXT_SIZE, 15 * heroScale)
  const heroIconSize = Math.max(HERO_MIN_ICON_SIZE, 20 * heroScale)
  const placeholderMeasureFontSize = isHero ? `${heroTextSize}px` : undefined
  const canFitPlaceholder = (candidate: string) => {
    if (!isHero) return true
    const measure = placeholderMeasureRef.current
    if (!measure || textAreaWidth <= 0) return false
    measure.textContent = candidate
    return measure.scrollWidth <= textAreaWidth
  }
  const placeholder = isSmall
    ? SHORT_PLACEHOLDER
    : isHero
      ? canFitPlaceholder(LONG_PLACEHOLDER)
        ? LONG_PLACEHOLDER
        : canFitPlaceholder(MEDIUM_PLACEHOLDER)
          ? MEDIUM_PLACEHOLDER
          : SHORT_PLACEHOLDER
      : LONG_PLACEHOLDER

  return (
    <div
      ref={wrapperRef}
      className={cn('relative', (isFocused || showDropdown) && 'z-20', className)}
    >
      {isFocused && (
        <div
          className={cn(
            'absolute bottom-full left-0 right-0 z-[1001] border-2 border-b-0 border-[#111111] bg-[#F0EDE6]',
            isTopBar && '-left-[2px] -right-[2px]'
          )}
        >
          <div className="relative flex items-center px-3 py-1.5">
            <div
              className={cn(
                'pointer-events-none absolute left-0 top-0 bottom-0 z-[1] w-10 bg-gradient-to-r from-[#F0EDE6] via-[#F0EDE6] to-transparent transition-opacity',
                canScrollSymbolsLeft ? 'opacity-100' : 'opacity-0'
              )}
            />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                scrollSymbols('left')
              }}
              className={cn(
                'absolute left-1.5 top-1/2 z-[2] -translate-y-1/2 text-[#111111] transition-opacity',
                canScrollSymbolsLeft
                  ? 'opacity-55 hover:opacity-100'
                  : 'pointer-events-none opacity-0'
              )}
              aria-label="Show previous symbols"
            >
              <CaretLeftIcon size={12} weight="bold" />
            </button>
            <div
              ref={symbolRailRef}
              className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto overflow-y-hidden whitespace-nowrap"
              style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
            >
              {SYMBOL_RAIL_ITEMS.map((item, index) =>
                item === '.' ? (
                  <span
                    key={`divider-${index}`}
                    className="shrink-0 text-[10px] text-[#111111]/25"
                    aria-hidden="true"
                  >
                    •
                  </span>
                ) : (
                  <button
                    key={item}
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault()
                      handleInsertSymbol(item)
                    }}
                    className="flex h-5 shrink-0 items-center justify-center text-[#111111] opacity-30 transition-opacity hover:opacity-100"
                    aria-label={`Insert ${item}`}
                    title={item}
                  >
                    <SymbolText
                      text={item}
                      className="flex-nowrap items-center text-[13px]"
                    />
                  </button>
                )
              )}
            </div>
            <div
              className={cn(
                'pointer-events-none absolute right-0 top-0 bottom-0 z-[1] w-10 bg-gradient-to-l from-[#F0EDE6] via-[#F0EDE6] to-transparent transition-opacity',
                canScrollSymbolsRight ? 'opacity-100' : 'opacity-0'
              )}
            />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                scrollSymbols('right')
              }}
              className={cn(
                'absolute right-1.5 top-1/2 z-[2] -translate-y-1/2 text-[#111111] transition-opacity',
                canScrollSymbolsRight
                  ? 'opacity-55 hover:opacity-100'
                  : 'pointer-events-none opacity-0'
              )}
              aria-label="Show more symbols"
            >
              <CaretRightIcon size={12} weight="bold" />
            </button>
          </div>
        </div>
      )}

      <label
          className={cn(
            'flex cursor-text items-center gap-3',
            isTopBar
              ? 'h-full bg-[#F0EDE6] px-3'
              : cn(
                'border-2 border-[#111111] bg-white',
                isCompact ? 'px-3 py-[10px]' : isHero ? '' : 'px-4 py-[18px]'
              )
          )}
          style={
            isHero
              ? {
                  paddingInline: `${heroHorizontalPadding}px`,
                  paddingBlock: `${heroVerticalPadding}px`,
                }
              : undefined
          }
          onMouseDown={(e) => {
            if (!editorRef.current) return
            if (e.target === editorRef.current || editorRef.current.contains(e.target as Node)) {
            return
          }
          e.preventDefault()
          focusEditorAt(query.length)
        }}
      >
        <MagnifyingGlassIcon
          className={cn(
            'shrink-0 text-[#111111]',
            isSmall || isHero ? '' : 'h-5 w-5'
          )}
          size={isHero ? heroIconSize : undefined}
          weight="bold"
        />
        <div ref={textAreaRef} className="relative min-w-0 flex-1">
          {isHero && (
            <span
              ref={placeholderMeasureRef}
              aria-hidden="true"
              className="pointer-events-none absolute invisible inset-0 overflow-hidden whitespace-nowrap font-mono"
              style={{ fontSize: placeholderMeasureFontSize }}
            />
          )}
          {!query && (
            <span
              className={cn(
                'pointer-events-none absolute inset-0 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[#ABABAB]',
                isHero ? '' : isSmall ? 'text-[13px]' : 'text-[15px]'
              )}
              style={isHero ? { fontSize: `${heroTextSize}px` } : undefined}
            >
              {placeholder}
            </span>
          )}
          <div
            ref={editorRef}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-label="Search"
            spellCheck={false}
            onInput={handleEditorInput}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              setIsFocused(true)
              if (hasDropdownContent) setIsOpen(true)
            }}
            onBlur={() => {
              pendingSelectionRef.current = null
            }}
            className={cn(
              'font-mono relative w-full overflow-hidden whitespace-nowrap bg-transparent text-[#111111] caret-[#111111] outline-none',
              isHero ? '' : isSmall ? 'text-[13px]' : 'text-[15px]'
            )}
            style={isHero ? { fontSize: `${heroTextSize}px` } : undefined}
          />
        </div>
      </label>

      {showDropdown && (
        <div
          className={cn(
            'absolute top-full z-[1000] flex flex-col border-2 border-t-0 border-[#111111] bg-white',
            isTopBar ? '-left-[2px] -right-[2px]' : 'left-0 right-0'
          )}
        >
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
                  <SymbolText text={card.name} className="flex-nowrap items-center gap-0" />
                </button>
              ))}
            </>
          )}

          {nameMatches.length > 0 &&
            (semanticMatches.length > 0 || isSemanticLoading) && (
              <div className="h-[2px] bg-[#F5C400]" />
            )}

          {(semanticMatches.length > 0 || isSemanticLoading) && (
            <>
              <div className="flex items-center justify-between border-b border-[#E8E5DE] px-4 py-2">
                <span className="font-display text-[9px] font-bold tracking-[0.18em] text-[#8B7A00] uppercase">
                  About &ldquo;<SymbolText text={displayQuery} className="inline-flex flex-nowrap items-center gap-0 align-baseline normal-case" />&rdquo;
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
                  <SymbolText text={card.name} className="flex-nowrap items-center gap-0" />
                  {card.type_line && (
                    <span className="ml-4 shrink-0 text-[11px] text-[#7A7670] hover:text-inherit">
                      {card.type_line.split('—')[0].trim()}
                    </span>
                  )}
                </button>
              ))}
            </>
          )}

          {(semanticMatches.length > 0 ||
            (nameMatches.length > 0 && !isSemanticLoading)) && (
            <>
              <div className="-mt-px h-[2px] bg-[#111111]" />
              <button
                onClick={handleSemanticSearch}
                className="font-display flex w-full cursor-pointer items-center justify-between px-4 py-3 text-[11px] font-bold tracking-[0.1em] text-[#111111] uppercase hover:bg-[#111111] hover:text-white"
              >
                <span>
                  See all results for &ldquo;<SymbolText text={displayQuery} className="inline-flex flex-nowrap items-center gap-0 align-baseline normal-case" />&rdquo;
                </span>
                <span>→</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
