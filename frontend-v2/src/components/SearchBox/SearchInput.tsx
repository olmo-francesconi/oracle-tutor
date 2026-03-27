import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ClipboardEvent,
  type KeyboardEvent,
} from 'react'
import { getManaClass, splitSymbolParts } from '../../lib/manaSymbols'

type SelectionRange = {
  start: number
  end: number
}

interface SearchInputProps {
  value: string
  autoFocus?: boolean
  onChange: (value: string) => void
  onSubmit: () => void
  onArrowNavigate: (direction: 'up' | 'down') => void
  onFocusChange: (focused: boolean) => void
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
    if (part.startsWith('{') && part.endsWith('}')) {
      const manaClass = getManaClass(part)
      if (manaClass) {
        const token = document.createElement('span')
        token.dataset.token = part
        token.contentEditable = 'false'
        token.className = 'search-token'

        const icon = document.createElement('i')
        icon.className = `${manaClass} search-token-icon`
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

export function SearchInput({
  value,
  autoFocus = false,
  onChange,
  onSubmit,
  onArrowNavigate,
  onFocusChange,
}: SearchInputProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const pendingSelectionRef = useRef<SelectionRange | null>(null)

  useEffect(() => {
    if (!autoFocus || !editorRef.current) return
    editorRef.current.focus()
    const end = value.length
    setSelectionRange(editorRef.current, end, end)
  }, [autoFocus, value.length])

  useLayoutEffect(() => {
    if (!editorRef.current) return

    buildEditableContent(editorRef.current, value)

    if (document.activeElement === editorRef.current) {
      const selection = pendingSelectionRef.current ?? {
        start: value.length,
        end: value.length,
      }
      setSelectionRange(editorRef.current, selection.start, selection.end)
    }
  }, [value])

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
    <label className="search-input-shell">
      <span className="control-label">Search</span>
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Search cards"
        spellCheck={false}
        onInput={handleInput}
        onPaste={handlePaste}
        onKeyDown={handleKeyDown}
        onFocus={() => onFocusChange(true)}
        onBlur={() => {
          pendingSelectionRef.current = null
          onFocusChange(false)
        }}
        className="search-editor"
        data-placeholder="type card text or insert mana symbols"
      />
    </label>
  )
}
