import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'
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
  enableTypeAhead?: boolean
  initialValue?: string
  size?: 'default' | 'compact' | 'topBar' | 'hero'
  heroScale?: number
  onDropdownChange?: (open: boolean) => void
  onDropdownHeightChange?: (height: number) => void
  onFocusChange?: (focused: boolean) => void
  onTypeAheadTrigger?: () => void
}

interface SearchInputEditorProps {
  query: string
  autoFocus?: boolean
  initialCaret: number
  size: UnifiedSearchBoxProps['size']
  heroHorizontalPadding: number
  heroVerticalPadding: number
  heroTextSize: number
  heroIconSize: number
  placeholder: string
  placeholderMeasureFontSize?: string
  placeholderMeasureRef: React.RefObject<HTMLSpanElement | null>
  className?: string
  onFocusChange: (focused: boolean) => void
  onOpenChange: (open: boolean) => void
  onArrowNavigate: (direction: 'up' | 'down') => void
  onQueryChange: (query: string) => void
  onSubmit: () => void
  onEscape: () => void
  onTextAreaWidthChange: (width: number) => void
  registerEditorCommandHandler: (handler: (command: EditorCommand) => void) => void
  registerInsertSymbolHandler: (handler: (symbol: string) => void) => void
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
const DROPDOWN_VIEWPORT_MARGIN = 12
const MIN_DROPDOWN_HEIGHT = 160
const PLACEHOLDER_ROWS = 4
const PLACEHOLDER_NAME_WIDTHS = ['15ch', '12ch', '10ch', '14ch'] as const
const PLACEHOLDER_TYPE_WIDTHS = ['9ch', '7ch', '10ch', '8ch'] as const

type EditorCommand =
  | { type: 'focus-end' }
  | { type: 'delete-last' }
  | { type: 'insert-text'; text: string }

type SelectableItem =
  | { id: string; type: 'name'; card: CardMatch }
  | { id: string; type: 'semantic'; card: SimilarCard }
  | { id: string; type: 'search' }

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

  return Array.from(node.childNodes).reduce(
    (total, childNode) => total + getNodeRawLength(childNode),
    0
  )
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

      return Array.from(node.childNodes)
        .map((childNode) => getNodeRawLength(childNode) ? readNodeRawText(childNode) : '')
        .join('')
    })
    .join('')
}

function readNodeRawText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? ''
  }

  if (node instanceof HTMLElement && node.dataset.token) {
    return node.dataset.token
  }

  return Array.from(node.childNodes).map(readNodeRawText).join('')
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
    if (node.contains(target)) {
      return total + getNestedRawOffset(node, target, offset)
    }

    if (node === target) {
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

function getNestedRawOffset(node: Node, target: Node, offset: number): number {
  if (node === target) {
    if (node.nodeType === Node.TEXT_NODE) {
      return offset
    }

    if (node instanceof HTMLElement && node.dataset.token) {
      return offset > 0 ? node.dataset.token.length : 0
    }
  }

  let total = 0
  for (const childNode of Array.from(node.childNodes)) {
    if (childNode === target || childNode.contains(target)) {
      return total + getNestedRawOffset(childNode, target, offset)
    }

    total += getNodeRawLength(childNode)
  }

  return total
}

function normalizePastedText(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\t/g, ' ')
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

function SearchInputEditor({
  query,
  autoFocus,
  initialCaret,
  size = 'default',
  heroHorizontalPadding,
  heroVerticalPadding,
  heroTextSize,
  heroIconSize,
  placeholder,
  placeholderMeasureFontSize,
  placeholderMeasureRef,
  className,
  onFocusChange,
  onOpenChange,
  onArrowNavigate,
  onQueryChange,
  onSubmit,
  onEscape,
  onTextAreaWidthChange,
  registerEditorCommandHandler,
  registerInsertSymbolHandler,
}: SearchInputEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const textAreaRef = useRef<HTMLDivElement>(null)
  const resizeFrameRef = useRef<number | null>(null)
  const pendingSelectionRef = useRef<SelectionRange | null>(null)

  const isCompact = size === 'compact'
  const isTopBar = size === 'topBar'
  const isHero = size === 'hero'
  const isSmall = isCompact || isTopBar

  const focusEditorAt = (position: number) => {
    requestAnimationFrame(() => {
      if (!editorRef.current) return
      editorRef.current.focus()
      setSelectionRange(editorRef.current, position, position)
    })
  }

  useEffect(() => {
    if (!autoFocus || !editorRef.current) return
    editorRef.current.focus()
    setSelectionRange(editorRef.current, initialCaret, initialCaret)
  }, [autoFocus, initialCaret])

  useEffect(() => {
    const updateTextAreaWidth = () => {
      onTextAreaWidthChange(textAreaRef.current?.clientWidth ?? 0)
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
  }, [onTextAreaWidthChange])

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

  const handleInsertSymbol = useCallback((symbol: string) => {
    const selection = editorRef.current
      ? getSelectionRange(editorRef.current)
      : { start: query.length, end: query.length }
    const nextQuery =
      query.slice(0, selection.start) + symbol + query.slice(selection.end)
    const nextCaret = selection.start + symbol.length

    pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
    onQueryChange(nextQuery)
    onFocusChange(true)
    focusEditorAt(nextCaret)
  }, [onFocusChange, onQueryChange, query])

  useEffect(() => {
    registerInsertSymbolHandler((symbol) => {
      handleInsertSymbol(symbol)
    })
  }, [handleInsertSymbol, registerInsertSymbolHandler])

  useEffect(() => {
    registerEditorCommandHandler((command) => {
      if (command.type === 'focus-end') {
        focusEditorAt(query.length)
        return
      }

      if (command.type === 'delete-last') {
        const nextQuery = query.slice(0, -1)
        const nextCaret = nextQuery.length

        pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
        onQueryChange(nextQuery)
        onOpenChange(nextQuery.trim().length > 0)
        onFocusChange(true)
        focusEditorAt(nextCaret)
        return
      }

      const selection = editorRef.current
        ? getSelectionRange(editorRef.current)
        : { start: query.length, end: query.length }
      const nextQuery =
        query.slice(0, selection.start) + command.text + query.slice(selection.end)
      const nextCaret = selection.start + command.text.length

      pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
      onQueryChange(nextQuery)
      onOpenChange(nextQuery.trim().length > 0)
      onFocusChange(true)
      focusEditorAt(nextCaret)
    })
  }, [focusEditorAt, onFocusChange, onOpenChange, onQueryChange, query, registerEditorCommandHandler])

  const handleEditorInput = () => {
    if (!editorRef.current) return

    const nextQuery = readRawQuery(editorRef.current)
    const nextSelection = getSelectionRange(editorRef.current)

    pendingSelectionRef.current = nextSelection
    onQueryChange(nextQuery)
    onOpenChange(nextQuery.trim().length > 0)
  }

  const handleEditorPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault()

    const pastedText = normalizePastedText(event.clipboardData.getData('text/plain'))
    if (!pastedText) return

    const selection = editorRef.current
      ? getSelectionRange(editorRef.current)
      : { start: query.length, end: query.length }
    const nextQuery =
      query.slice(0, selection.start) + pastedText + query.slice(selection.end)
    const nextCaret = selection.start + pastedText.length

    pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
    onQueryChange(nextQuery)
    onOpenChange(nextQuery.trim().length > 0)
    focusEditorAt(nextCaret)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      onArrowNavigate(event.key === 'ArrowDown' ? 'down' : 'up')
    } else if (event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    } else if (event.key === 'Escape') {
      onOpenChange(false)
      onFocusChange(false)
      editorRef.current?.blur()
      onEscape()
    }
  }

  return (
    <label
      className={cn(
        'flex cursor-text items-center gap-3',
        isTopBar
          ? 'h-full bg-[#F0EDE6] px-3'
          : cn(
            'border-2 border-[#111111] bg-white',
            isCompact ? 'px-3 py-[10px]' : isHero ? '' : 'px-4 py-[18px]'
          ),
        className
      )}
      style={
        isHero
          ? {
              paddingInline: `${heroHorizontalPadding}px`,
              paddingBlock: `${heroVerticalPadding}px`,
            }
          : undefined
      }
      onMouseDown={(event) => {
        if (!editorRef.current) return
        if (
          event.target === editorRef.current ||
          editorRef.current.contains(event.target as Node)
        ) {
          return
        }
        event.preventDefault()
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
          onPaste={handleEditorPaste}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            onFocusChange(true)
            if (query.trim().length > 0) onOpenChange(true)
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
  )
}

export function UnifiedSearchBox({
  className,
  autoFocus,
  enableTypeAhead = false,
  initialValue = '',
  size = 'default',
  heroScale = 1,
  onDropdownChange,
  onDropdownHeightChange,
  onFocusChange,
  onTypeAheadTrigger,
}: UnifiedSearchBoxProps) {
  const [query, setQuery] = useState(initialValue)
  const [nameMatches, setNameMatches] = useState<CardMatch[]>([])
  const [semanticMatches, setSemanticMatches] = useState<SimilarCard[]>([])
  const [isNameLoading, setIsNameLoading] = useState(false)
  const [isSemanticLoading, setIsSemanticLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [canTrackPointerSelection, setCanTrackPointerSelection] = useState(false)
  const [canScrollSymbolsLeft, setCanScrollSymbolsLeft] = useState(false)
  const [canScrollSymbolsRight, setCanScrollSymbolsRight] = useState(false)
  const initialCaretRef = useRef(initialValue.length)
  const navigate = useNavigate()
  const symbolRailRef = useRef<HTMLDivElement>(null)
  const placeholderMeasureRef = useRef<HTMLSpanElement>(null)
  const insertSymbolHandlerRef = useRef<(symbol: string) => void>(() => {})
  const [textAreaWidth, setTextAreaWidth] = useState(0)
  const [dropdownMaxHeight, setDropdownMaxHeight] = useState<number | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const editorCommandHandlerRef = useRef<(command: EditorCommand) => void>(() => {})
  const selectableItemRefs = useRef<Array<HTMLButtonElement | null>>([])
  const lastPointerPositionRef = useRef<{ x: number; y: number } | null>(null)
  const pointerUnlockOriginRef = useRef<{ x: number; y: number } | null>(null)
  const queryTrimmed = query.trim()

  useEffect(() => {
    const handleDocumentMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setIsFocused(false)
      }
    }

    document.addEventListener('mousedown', handleDocumentMouseDown)

    return () => {
      document.removeEventListener('mousedown', handleDocumentMouseDown)
    }
  }, [])

  useEffect(() => {
    if (queryTrimmed.length < 2) {
      setNameMatches([])
      setIsNameLoading(false)
      return
    }

    setIsNameLoading(true)
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const results = await searchCards(query, 6, 0, controller.signal)
        if (!controller.signal.aborted) {
          setNameMatches(results)
        }
      } catch {
        // silently ignore aborted requests
      } finally {
        if (!controller.signal.aborted) {
          setIsNameLoading(false)
        }
      }
    }, 250)

    return () => {
      clearTimeout(timer)
      controller.abort()
      setIsNameLoading(false)
    }
  }, [query, queryTrimmed.length])

  useEffect(() => {
    if (queryTrimmed.length < 3) {
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
  }, [query, queryTrimmed.length])

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

  const showDropdown = isOpen && queryTrimmed.length > 0
  const showNameLoadingState = queryTrimmed.length > 0 && (queryTrimmed.length < 2 || isNameLoading)
  const showSemanticSection =
    queryTrimmed.length >= 3 || semanticMatches.length > 0 || isSemanticLoading
  const selectableItems = useMemo<SelectableItem[]>(() => {
    const items: SelectableItem[] = [
      ...nameMatches.slice(0, 6).map((card) => ({
        id: `name-${card.oracle_id ?? card.name}-${card.face_ix}`,
        type: 'name' as const,
        card,
      })),
      ...semanticMatches.slice(0, 4).map((card) => ({
        id: `semantic-${card.oracle_id}`,
        type: 'semantic' as const,
        card,
      })),
    ]

    if (queryTrimmed.length > 0) {
      items.push({ id: `search-${queryTrimmed}`, type: 'search' })
    }

    return items
  }, [nameMatches, queryTrimmed, semanticMatches])
  const selectableSignature = selectableItems.map((item) => item.id).join('|')

  useEffect(() => {
    onDropdownChange?.(showDropdown)
  }, [showDropdown, onDropdownChange])

  useEffect(() => {
    if (!showDropdown || size !== 'hero') {
      onDropdownHeightChange?.(0)
      return
    }

    const node = dropdownRef.current
    if (!node) return

    const updateHeight = () => {
      const { bottom } = node.getBoundingClientRect()
      onDropdownHeightChange?.(bottom)
    }

    updateHeight()

    const observer = new ResizeObserver(updateHeight)
    observer.observe(node)

    return () => observer.disconnect()
  }, [onDropdownHeightChange, showDropdown, size, nameMatches, semanticMatches, isSemanticLoading, query])

  useEffect(() => {
    onFocusChange?.(isFocused)
  }, [isFocused, onFocusChange])

  useEffect(() => {
    if (!isFocused) {
      setIsOpen(false)
      setActiveIndex(-1)
      return
    }

    setIsOpen(queryTrimmed.length > 0)
  }, [isFocused, queryTrimmed.length])

  useEffect(() => {
    setActiveIndex(-1)
  }, [queryTrimmed, selectableSignature, showDropdown])

  useEffect(() => {
    const recordPointerPosition = (event: PointerEvent) => {
      lastPointerPositionRef.current = { x: event.clientX, y: event.clientY }
    }

    window.addEventListener('pointermove', recordPointerPosition, { passive: true })

    return () => {
      window.removeEventListener('pointermove', recordPointerPosition)
    }
  }, [])

  useEffect(() => {
    if (!showDropdown) {
      setCanTrackPointerSelection(false)
      pointerUnlockOriginRef.current = null
      return
    }

    setCanTrackPointerSelection(false)
    pointerUnlockOriginRef.current = lastPointerPositionRef.current

    const enablePointerSelection = (event: PointerEvent) => {
      const origin = pointerUnlockOriginRef.current
      const hasMoved =
        !origin ||
        origin.x !== event.clientX ||
        origin.y !== event.clientY

      lastPointerPositionRef.current = { x: event.clientX, y: event.clientY }
      if (!hasMoved) return

      setCanTrackPointerSelection(true)
    }

    window.addEventListener('pointermove', enablePointerSelection, { passive: true })

    return () => {
      window.removeEventListener('pointermove', enablePointerSelection)
    }
  }, [showDropdown, queryTrimmed, selectableSignature])

  useEffect(() => {
    if (activeIndex < 0) return
    selectableItemRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  useEffect(() => {
    if (!enableTypeAhead) return

    const isEditableTarget = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false
      if (target.isContentEditable) return true
      return target.closest('input, textarea, select, [contenteditable="true"]') instanceof HTMLElement
    }

    const handleWindowKeyDown = (event: globalThis.KeyboardEvent) => {
      const hasBlockedModifier = event.metaKey || event.ctrlKey

      if (event.defaultPrevented || hasBlockedModifier) return
      if (isEditableTarget(event.target)) return

      if (event.key === 'Backspace' || event.key === 'Delete') {
        event.preventDefault()
        onTypeAheadTrigger?.()
        setIsFocused(true)
        setIsOpen(true)
        editorCommandHandlerRef.current({ type: 'delete-last' })
        return
      }

      const typedCharacter =
        event.key.length === 1
          ? event.key
          : event.shiftKey && event.code === 'BracketLeft'
            ? '{'
            : event.shiftKey && event.code === 'BracketRight'
              ? '}'
              : null

      if (!typedCharacter) return

      event.preventDefault()
      onTypeAheadTrigger?.()
      setIsFocused(true)
      setIsOpen(true)
      editorCommandHandlerRef.current({ type: 'insert-text', text: typedCharacter })
    }

    window.addEventListener('keydown', handleWindowKeyDown)
    return () => window.removeEventListener('keydown', handleWindowKeyDown)
  }, [enableTypeAhead, onTypeAheadTrigger])

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

  useEffect(() => {
    if (!showDropdown || size === 'hero') {
      setDropdownMaxHeight(null)
      return
    }

    const updateDropdownMaxHeight = () => {
      const root = rootRef.current
      if (!root) return

      const { bottom } = root.getBoundingClientRect()
      const availableHeight = window.innerHeight - bottom - DROPDOWN_VIEWPORT_MARGIN
      setDropdownMaxHeight(Math.max(Math.floor(availableHeight), MIN_DROPDOWN_HEIGHT))
    }

    updateDropdownMaxHeight()
    window.addEventListener('resize', updateDropdownMaxHeight)
    window.addEventListener('scroll', updateDropdownMaxHeight, { passive: true })

    return () => {
      window.removeEventListener('resize', updateDropdownMaxHeight)
      window.removeEventListener('scroll', updateDropdownMaxHeight)
    }
  }, [showDropdown, size])

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

  const activateItem = useCallback((item: SelectableItem) => {
    if (item.type === 'name') {
      handleNameSelect(item.card)
      return
    }

    if (item.type === 'semantic') {
      handleSemanticSelect(item.card)
      return
    }

    handleSemanticSearch()
  }, [handleSemanticSearch])

  const handleArrowNavigate = (direction: 'up' | 'down') => {
    if (!showDropdown || selectableItems.length === 0) return

    setActiveIndex((current) => {
      if (direction === 'down') {
        return current < 0 ? 0 : Math.min(current + 1, selectableItems.length - 1)
      }

      if (current <= 0) return 0
      return current - 1
    })
  }

  const handlePointerSelection = (index: number) => {
    if (!canTrackPointerSelection) return
    setActiveIndex(index)
  }

  const pointerHoverClasses = canTrackPointerSelection
    ? 'hover:bg-[#111111] hover:text-white'
    : ''

  return (
    <div
      ref={rootRef}
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
                      insertSymbolHandlerRef.current(item)
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

      <SearchInputEditor
        query={query}
        autoFocus={autoFocus}
        initialCaret={initialCaretRef.current}
        size={size}
        heroHorizontalPadding={heroHorizontalPadding}
        heroVerticalPadding={heroVerticalPadding}
        heroTextSize={heroTextSize}
        heroIconSize={heroIconSize}
        placeholder={placeholder}
        placeholderMeasureFontSize={placeholderMeasureFontSize}
        placeholderMeasureRef={placeholderMeasureRef}
        onFocusChange={setIsFocused}
        onOpenChange={setIsOpen}
        onArrowNavigate={handleArrowNavigate}
        onQueryChange={setQuery}
        onSubmit={() => {
          const activeItem = activeIndex >= 0 ? selectableItems[activeIndex] : null
          if (activeItem) {
            activateItem(activeItem)
            return
          }

          const exact = nameMatches.find(
            (card) => card.name.toLowerCase() === queryTrimmed.toLowerCase()
          )
          if (exact) {
            handleNameSelect(exact)
          } else {
            handleSemanticSearch()
          }
        }}
        onEscape={() => {
          setIsOpen(false)
          setIsFocused(false)
        }}
        onTextAreaWidthChange={setTextAreaWidth}
        registerEditorCommandHandler={(handler) => {
          editorCommandHandlerRef.current = handler
        }}
        registerInsertSymbolHandler={(handler) => {
          insertSymbolHandlerRef.current = handler
        }}
      />

      {showDropdown && (
        <div
          ref={dropdownRef}
          className={cn(
            'z-[1000] flex flex-col border-2 border-t-0 border-[#111111] bg-white',
            isHero
              ? 'absolute left-0 right-0 top-full'
              : cn(
                  'absolute top-full overflow-y-auto overscroll-contain',
                  isTopBar ? '-left-[2px] -right-[2px]' : 'left-0 right-0'
                )
          )}
          style={!isHero && dropdownMaxHeight ? { maxHeight: `${dropdownMaxHeight}px` } : undefined}
        >
          {(nameMatches.length > 0 || showNameLoadingState) && (
            <>
              <div className="border-b border-[#E8E5DE] px-4 py-2">
                <span className="font-display text-[9px] font-bold tracking-[0.18em] text-[#7A7670] uppercase">
                  Cards
                </span>
              </div>
              {nameMatches.slice(0, 6).map((card, index) => (
                <button
                  key={`name-${card.oracle_id ?? card.name}-${card.face_ix}`}
                  ref={(element) => {
                    selectableItemRefs.current[index] = element
                  }}
                  onClick={() => handleNameSelect(card)}
                  onMouseMove={() => handlePointerSelection(index)}
                  className={cn(
                    'font-mono flex w-full cursor-pointer items-center px-4 py-3 text-left text-[13px] text-[#111111]',
                    pointerHoverClasses,
                    activeIndex === index && 'bg-[#111111] text-white'
                  )}
                >
                  <SymbolText text={card.name} className="flex-nowrap items-center gap-0" />
                </button>
              ))}
              {nameMatches.length === 0 && showNameLoadingState && (
                <div className="transition-opacity duration-150">
                  {Array.from(
                    { length: Math.min(PLACEHOLDER_ROWS, Math.max(queryTrimmed.length, 1) + 1) },
                    (_, index) => (
                      <div
                        key={`name-placeholder-${index}`}
                        className="font-mono flex items-center px-4 py-3 text-left text-[13px] leading-[1.2] text-[#111111]"
                      >
                        <span
                          className="block h-[0.92em] animate-pulse bg-[#F0EDE6]"
                          style={{ width: PLACEHOLDER_NAME_WIDTHS[index % PLACEHOLDER_NAME_WIDTHS.length] }}
                        />
                      </div>
                    )
                  )}
                </div>
              )}
            </>
          )}

          {(nameMatches.length > 0 || showNameLoadingState) &&
            showSemanticSection && (
              <div className="h-[2px] bg-[#F5C400]" />
            )}

          {showSemanticSection && (
            <>
              <div className="flex items-center justify-between border-b border-[#E8E5DE] px-4 py-2">
                <span className="font-display text-[9px] font-bold tracking-[0.18em] text-[#8B7A00] uppercase">
                  About &ldquo;<SymbolText text={displayQuery} className="inline-flex flex-nowrap items-center gap-0 align-baseline normal-case" />&rdquo;
                </span>
                {queryTrimmed.length < 3 ? (
                  <span className="font-mono text-[10px] text-[#ABABAB]">
                    type more…
                  </span>
                ) : isSemanticLoading && (
                  <span className="font-mono text-[10px] text-[#ABABAB]">
                    searching…
                  </span>
                )}
              </div>
              {semanticMatches.slice(0, 4).map((card, index) => {
                const selectableIndex = nameMatches.slice(0, 6).length + index

                return (
                  <button
                    key={`semantic-${card.oracle_id}`}
                    ref={(element) => {
                      selectableItemRefs.current[selectableIndex] = element
                    }}
                    onClick={() => handleSemanticSelect(card)}
                    onMouseMove={() => handlePointerSelection(selectableIndex)}
                    className={cn(
                      'font-mono flex w-full cursor-pointer items-center justify-between border-b border-[#F0EDE6] px-4 py-3 text-left text-[13px] text-[#111111] last:border-b-0',
                      pointerHoverClasses,
                      activeIndex === selectableIndex && 'bg-[#111111] text-white'
                    )}
                  >
                    <SymbolText text={card.name} className="flex-nowrap items-center gap-0" />
                    {card.type_line && (
                      <span className={cn('ml-4 shrink-0 text-[11px] text-[#7A7670]', canTrackPointerSelection && 'hover:text-inherit')}>
                        {card.type_line.split('—')[0].trim()}
                      </span>
                    )}
                  </button>
                )
              })}
              {semanticMatches.length === 0 && queryTrimmed.length >= 3 && isSemanticLoading && (
                <div className="transition-opacity duration-150">
                  {Array.from({ length: PLACEHOLDER_ROWS }, (_, index) => (
                    <div
                      key={`semantic-placeholder-${index}`}
                      className="font-mono flex items-center justify-between border-b border-[#F0EDE6] px-4 py-3 text-left text-[13px] leading-[1.2] text-[#111111] last:border-b-0"
                    >
                      <span
                        className="block h-[0.92em] animate-pulse bg-[#F0EDE6]"
                        style={{ width: PLACEHOLDER_NAME_WIDTHS[index % PLACEHOLDER_NAME_WIDTHS.length] }}
                      />
                      <span
                        className="ml-4 block h-[11px] shrink-0 self-center animate-pulse bg-[#F0EDE6]"
                        style={{ width: PLACEHOLDER_TYPE_WIDTHS[index % PLACEHOLDER_TYPE_WIDTHS.length] }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {queryTrimmed.length > 0 && (
            <>
              <div className="-mt-px h-[2px] bg-[#111111]" />
              <button
                ref={(element) => {
                  selectableItemRefs.current[selectableItems.length - 1] = element
                }}
                onClick={handleSemanticSearch}
                onMouseMove={() => handlePointerSelection(selectableItems.length - 1)}
                className={cn(
                  'font-display flex w-full cursor-pointer items-center justify-between px-4 py-3 text-[11px] font-bold tracking-[0.1em] text-[#111111] uppercase',
                  pointerHoverClasses,
                  activeIndex === selectableItems.length - 1 && 'bg-[#111111] text-white'
                )}
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
