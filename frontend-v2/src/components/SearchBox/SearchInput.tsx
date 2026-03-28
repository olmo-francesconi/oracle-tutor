import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ClipboardEvent,
  type KeyboardEvent,
} from 'react'
import { getManaClass, isSupportedManaSymbol, splitSymbolParts } from '../../lib/manaSymbols'

type SelectionRange = {
  start: number
  end: number
}

interface SearchInputProps {
  value: string
  autoFocus?: boolean
  variant: 'home' | 'topbar'
  activeIndex: number
  suggestionsId: string
  suggestionsOpen: boolean
  pendingInsert: {
    id: number
    symbol: string
  } | null
  onChange: (value: string) => void
  onSubmit: () => void
  onArrowNavigate: (direction: 'up' | 'down') => void
  onFocusChange: (focused: boolean) => void
  onInsertHandled: () => void
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

  splitSymbolParts(text).forEach((part) => {
    if (isSupportedManaSymbol(part)) {
      const manaClass = getManaClass(part)
      if (manaClass) {
        const token = document.createElement('span')
        token.dataset.token = part
        token.contentEditable = 'false'
        token.className = 'inline-flex items-center align-middle'

        const icon = document.createElement('i')
        icon.className = `${manaClass} ms-cost inline-block align-middle text-[0.9em] leading-none`
        icon.setAttribute('title', part)
        icon.setAttribute('aria-label', part)

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
        .map((childNode) => readNodeRawText(childNode))
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

function normalizePastedText(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\t/g, ' ')
}

function restoreSelection(
  editor: HTMLDivElement | null,
  selection: SelectionRange | null,
  fallbackLength: number
) {
  if (!editor) return

  const nextSelection = selection ?? {
    start: fallbackLength,
    end: fallbackLength,
  }

  setSelectionRange(editor, nextSelection.start, nextSelection.end)
}

export function SearchInput({
  value,
  autoFocus = false,
  variant,
  activeIndex,
  suggestionsId,
  suggestionsOpen,
  pendingInsert,
  onChange,
  onSubmit,
  onArrowNavigate,
  onFocusChange,
  onInsertHandled,
}: SearchInputProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const pendingSelectionRef = useRef<SelectionRange | null>(null)

  useEffect(() => {
    if (!autoFocus || !editorRef.current) return
    editorRef.current.focus()
    pendingSelectionRef.current = {
      start: value.length,
      end: value.length,
    }
    restoreSelection(editorRef.current, pendingSelectionRef.current, value.length)
  }, [autoFocus, value.length])

  useLayoutEffect(() => {
    if (!editorRef.current) return

    buildEditableContent(editorRef.current, value)

    if (document.activeElement === editorRef.current) {
      restoreSelection(editorRef.current, pendingSelectionRef.current, value.length)
    }
  }, [value, value.length])

  useEffect(() => {
    if (!pendingInsert || !editorRef.current) return

    const editor = editorRef.current
    const selection =
      document.activeElement === editor
        ? getSelectionRange(editor)
        : { start: value.length, end: value.length }
    const nextValue =
      value.slice(0, selection.start) + pendingInsert.symbol + value.slice(selection.end)
    const nextCaret = selection.start + pendingInsert.symbol.length

    pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
    editor.focus()
    onChange(nextValue)
    onFocusChange(true)
    onInsertHandled()
  }, [onChange, onFocusChange, onInsertHandled, pendingInsert, value])

  const handleInput = () => {
    if (!editorRef.current) return

    const nextValue = readRawQuery(editorRef.current)
    pendingSelectionRef.current = getSelectionRange(editorRef.current)
    onChange(nextValue)
  }

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault()

    const pastedText = normalizePastedText(event.clipboardData.getData('text/plain'))
    if (!pastedText || !editorRef.current) return

    const selection = getSelectionRange(editorRef.current)
    const nextValue =
      value.slice(0, selection.start) + pastedText + value.slice(selection.end)
    const nextCaret = selection.start + pastedText.length

    pendingSelectionRef.current = { start: nextCaret, end: nextCaret }
    onChange(nextValue)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      onArrowNavigate(event.key === 'ArrowDown' ? 'down' : 'up')
      return
    }

    if (event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
      return
    }

    if (event.key === 'Escape') {
      editorRef.current?.blur()
    }
  }

  return (
    <label className="grid w-full min-w-0 gap-0">
      <span className="sr-only">Search</span>
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Search cards"
        aria-autocomplete="list"
        aria-expanded={suggestionsOpen}
        aria-controls={suggestionsOpen ? suggestionsId : undefined}
        aria-activedescendant={suggestionsOpen && activeIndex >= 0 ? `${suggestionsId}-option-${activeIndex}` : undefined}
        spellCheck={false}
        onInput={handleInput}
        onPaste={handlePaste}
        onKeyDown={handleKeyDown}
        onFocus={() => {
          restoreSelection(editorRef.current, pendingSelectionRef.current, value.length)
          onFocusChange(true)
        }}
        onBlur={() => {
          if (editorRef.current) {
            pendingSelectionRef.current = getSelectionRange(editorRef.current)
          }
          onFocusChange(false)
        }}
        className={[
          'search-editor w-full min-w-0 overflow-x-auto overflow-y-hidden whitespace-nowrap border-2 border-ot-ink bg-ot-surface text-ot-ink caret-ot-red outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
          'box-border',
          variant === 'topbar'
            ? 'flex h-full min-h-full items-center border-x-0 border-y-0 bg-ot-surface px-[22px] py-0 text-sm leading-[1.3] max-[720px]:px-[14px] max-[720px]:text-[0.8125rem]'
            : 'h-14 min-h-14 px-[18px] py-4 text-base leading-[1.45]',
        ].join(' ')}
        data-placeholder="search for a card or describe what it does…"
        data-variant={variant}
      />
    </label>
  )
}
