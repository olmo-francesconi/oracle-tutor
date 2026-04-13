import { useEffect, useId, useMemo, useRef, useState } from 'react'

type FilterChecklistProps = {
  label: string
  options: readonly string[]
  value: string[] | undefined
  placeholder: string
  minWidthClassName?: string
  onChange: (nextValue: string[] | undefined) => void
  formatOptionLabel?: (option: string) => string
}

const EMPTY_SELECTION: string[] = []

function defaultFormatOptionLabel(option: string): string {
  return option.charAt(0).toUpperCase() + option.slice(1)
}

function buildSummary(
  selected: string[],
  placeholder: string,
  formatOptionLabel: (option: string) => string
): string {
  if (selected.length === 0) return placeholder
  if (selected.length === 1) return formatOptionLabel(selected[0])
  if (selected.length === 2) return selected.map(formatOptionLabel).join(', ')
  return `${selected.length} selected`
}

export function FilterChecklist({
  label,
  options,
  value,
  placeholder,
  minWidthClassName = 'sm:min-w-[184px]',
  onChange,
  formatOptionLabel = defaultFormatOptionLabel,
}: FilterChecklistProps) {
  const [isOpen, setIsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelId = useId()
  const selected = value ?? EMPTY_SELECTION

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      setIsOpen(false)
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleEscape)

    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [])

  const summary = useMemo(
    () => buildSummary(selected, placeholder, formatOptionLabel),
    [formatOptionLabel, placeholder, selected]
  )

  return (
    <div ref={rootRef} className={`relative min-w-0 ${minWidthClassName}`}>
      <button
        type="button"
        className={[
          'flex h-10 w-full items-center justify-between border-2 px-3 text-left font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
          isOpen || selected.length > 0
            ? 'border-ot-ink bg-white text-ot-ink'
            : 'border-ot-ink bg-white text-ot-ink',
        ].join(' ')}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={panelId}
        aria-label={label}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="truncate pr-3">{summary}</span>
        <span className="text-[0.75rem]" aria-hidden="true">
          {isOpen ? '−' : '+'}
        </span>
      </button>

      {isOpen ? (
        <div
          id={panelId}
          className="absolute left-0 top-full z-30 grid w-full min-w-[184px] border-2 border-t-0 border-ot-ink bg-ot-surface"
          role="listbox"
          aria-multiselectable="true"
        >
          {options.map((option, index) => {
            const isSelected = selected.includes(option)
            const nextLabel = formatOptionLabel(option)

            return (
              <button
                key={option}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={[
                  'flex min-h-10 items-center gap-3 border-0 bg-ot-surface px-3 py-2 text-left font-body text-[0.8125rem] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                  index === 0 ? '' : 'border-t-2 border-ot-line',
                  'hover:bg-ot-bg',
                ].join(' ')}
                onClick={() => {
                  const nextValue = selected.includes(option)
                    ? selected.filter((value) => value !== option)
                    : [...selected, option]

                  onChange(nextValue.length > 0 ? nextValue : undefined)
                }}
              >
                <span className="flex h-3.5 w-3.5 flex-none items-center justify-center border-2 border-ot-ink" aria-hidden="true">
                  {isSelected ? <span className="h-1.5 w-1.5 bg-ot-red" /> : null}
                </span>
                <span className="truncate">{nextLabel}</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
