import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ClipboardEvent,
  type KeyboardEvent,
} from 'react'
import { getManaClass, isSupportedManaSymbol, splitSymbolParts } from '../../lib/manaSymbols'

// Zero-width-space anchor inserted after every non-editable token span so
// the browser has a stable text-node caret anchor adjacent to the token.
// Without it, when content ends with (or is bounded by) a contenteditable=
// false span Chrome can't place a usable caret, leaving the field stuck
// after auto-substitution. Anchors are invisible and stripped from the
// reported raw value.
const ANCHOR = '\u200B'
const ANCHOR_RE = /\u200B/g

type SelectionRange = {
  start: number
  end: number
}

function stripAnchors(text: string): string {
  return text.replace(ANCHOR_RE, '')
}

function countAnchorsBefore(text: string, offset: number): number {
  let count = 0
  for (let i = 0; i < offset && i < text.length; i += 1) {
    if (text[i] === ANCHOR) count += 1
  }
  return count
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
    return stripAnchors(node.textContent ?? '').length
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

  if (text === '') {
    // Leave the editor truly empty (no DOM children). Browsers only paint
    // the caret reliably on a contenteditable that's either empty or has
    // real editable text — adding a ZWSP, <br>, or non-editable span
    // breaks Chrome and Safari's caret rendering. The placeholder is
    // rendered as a CSS ::before pseudo (see styles.css) which doesn't
    // affect the :empty state.
    root.replaceChildren(fragment)
    return
  }

  splitSymbolParts(text).forEach((part) => {
    if (isSupportedManaSymbol(part)) {
      const manaClass = getManaClass(part)
      if (manaClass) {
        const token = document.createElement('span')
        token.dataset.token = part
        token.contentEditable = 'false'
        token.className = 'inline-flex items-center px-[0.07em] align-middle'

        const icon = document.createElement('i')
        icon.className = `${manaClass} ms-cost inline-block align-middle text-[0.9em] leading-none`
        icon.setAttribute('title', part)
        icon.setAttribute('aria-label', part)

        token.appendChild(icon)
        fragment.appendChild(token)
        fragment.appendChild(document.createTextNode(ANCHOR))
        return
      }
    }

    fragment.appendChild(document.createTextNode(part))
  })

  root.replaceChildren(fragment)
}

function readNodeRawText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return stripAnchors(node.textContent ?? '')
  }

  if (node instanceof HTMLElement && node.dataset.token) {
    return node.dataset.token
  }

  return Array.from(node.childNodes).map(readNodeRawText).join('')
}

function readRawQuery(root: HTMLDivElement): string {
  return Array.from(root.childNodes)
    .map((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        return stripAnchors(node.textContent ?? '')
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

function rawOffsetWithinTextNode(node: Node, offset: number): number {
  const text = node.textContent ?? ''
  const clamped = Math.min(offset, text.length)
  return clamped - countAnchorsBefore(text, clamped)
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
        return total + rawOffsetWithinTextNode(node, offset)
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
      return rawOffsetWithinTextNode(node, offset)
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

function mapRawOffsetToTextNodeOffset(text: string, rawOffsetInNode: number): number {
  let domOffset = 0
  let countedRaw = 0
  while (domOffset < text.length && countedRaw < rawOffsetInNode) {
    if (text[domOffset] !== ANCHOR) countedRaw += 1
    domOffset += 1
  }
  // After landing on the target raw offset, skip any anchor chars at this
  // position so the caret sits on a real text position rather than on an
  // anchor boundary (which Chrome handles inconsistently).
  while (domOffset < text.length && text[domOffset] === ANCHOR) {
    domOffset += 1
  }
  return domOffset
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
        const text = node.textContent ?? ''
        const offsetInNode = mapRawOffsetToTextNodeOffset(text, rawOffset - total)
        return { node, offset: offsetInNode }
      }

      if (node instanceof HTMLElement && node.dataset.token) {
        if (rawOffset <= total) {
          return { node: root, offset: index }
        }

        if (rawOffset <= total + length) {
          // Prefer an adjacent text node as the caret anchor; the builder
          // always inserts an anchor text node after a token, so this
          // virtually always lands inside that anchor node.
          const nextNode = nodes[index + 1]
          if (nextNode && nextNode.nodeType === Node.TEXT_NODE) {
            const text = nextNode.textContent ?? ''
            const offsetInNode = mapRawOffsetToTextNodeOffset(text, 0)
            return { node: nextNode, offset: offsetInNode }
          }
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

    const editor = editorRef.current
    const nextValue = readRawQuery(editor)
    pendingSelectionRef.current = getSelectionRange(editor)
    onChange(nextValue)

    // If the raw value didn't change (e.g. the browser stripped an anchor
    // character via Backspace/Delete without affecting visible text), React
    // won't re-render and the layout effect won't rebuild the canonical
    // structure. Rebuild synchronously so anchors always exist and the
    // caret stays on a real text node.
    if (nextValue === value) {
      buildEditableContent(editor, nextValue)
      restoreSelection(editor, pendingSelectionRef.current, nextValue.length)
    }
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
    if (
      event.key === 'Backspace' &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      !event.shiftKey &&
      editorRef.current
    ) {
      const editor = editorRef.current
      const sel = getSelectionRange(editor)
      if (sel.start === sel.end) {
        // Collapsed cursor at raw position 0: nothing in the value to
        // delete. Swallow the keystroke so the browser doesn't strip our
        // invisible anchor character and leave the caret without an anchor.
        if (sel.start === 0) {
          event.preventDefault()
          return
        }
        // Collapsed cursor right after a mana token → delete the entire
        // token in one keystroke. Without this, the default Backspace
        // first removes the invisible anchor character and only deletes
        // the token on the second press.
        let pos = 0
        for (const part of splitSymbolParts(value)) {
          const partEnd = pos + part.length
          if (partEnd === sel.start && isSupportedManaSymbol(part)) {
            event.preventDefault()
            const nextValue = value.slice(0, pos) + value.slice(sel.end)
            pendingSelectionRef.current = { start: pos, end: pos }
            onChange(nextValue)
            return
          }
          pos = partEnd
        }
      }
    }

    if (
      (event.key === 'ArrowLeft' || event.key === 'ArrowRight') &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      !event.shiftKey &&
      editorRef.current
    ) {
      const editor = editorRef.current
      const sel = getSelectionRange(editor)
      if (sel.start === sel.end) {
        // Step over the entire mana token in one keystroke. Without this,
        // the user presses arrow twice (once to traverse the invisible
        // anchor character, again to traverse the token).
        let pos = 0
        for (const part of splitSymbolParts(value)) {
          const partEnd = pos + part.length
          if (isSupportedManaSymbol(part)) {
            if (event.key === 'ArrowLeft' && partEnd === sel.start) {
              event.preventDefault()
              pendingSelectionRef.current = { start: pos, end: pos }
              setSelectionRange(editor, pos, pos)
              return
            }
            if (event.key === 'ArrowRight' && pos === sel.start) {
              event.preventDefault()
              pendingSelectionRef.current = { start: partEnd, end: partEnd }
              setSelectionRange(editor, partEnd, partEnd)
              return
            }
          }
          pos = partEnd
        }
      }
    }

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
          // Block + padding for vertical centering. Flex+items-center fails
          // for an EMPTY contenteditable (no flex items → no cross-axis
          // content → caret renders at top, not center). Block layout gives
          // the empty editor a natural line box at line-height, and the
          // padding-y values are chosen so that line sits at the editor's
          // vertical center.
          variant === 'topbar'
            ? 'block h-full min-h-full border-x-0 border-y-0 bg-ot-surface px-[22px] py-5 text-sm leading-[1.3] max-[720px]:px-[14px] max-[720px]:py-[20px] max-[720px]:text-[0.8125rem]'
            : 'block h-14 min-h-14 px-[18px] py-[14px] text-base leading-[1.45]',
        ].join(' ')}
        data-placeholder="search for a card or describe what it does…"
        data-variant={variant}
      />
    </label>
  )
}
