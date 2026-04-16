import { useEffect, useId, useRef, useState } from 'react'

type AdminSelectProps = {
  label: string
  options: { value: string; label: string }[]
  value: string
  placeholder: string
  onChange: (value: string) => void
}

export function AdminSelect({ label, options, value, placeholder, onChange }: AdminSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelId = useId()

  const selectedLabel = options.find((o) => o.value === value)?.label ?? placeholder

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      setIsOpen(false)
    }
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false)
    }
    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleEscape)
    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [])

  return (
    <div ref={rootRef} className="relative min-w-0">
      <button
        type="button"
        className="flex h-10 w-full items-center justify-between border-2 border-ot-ink bg-ot-bg px-3 text-left font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={panelId}
        aria-label={label}
        onClick={() => setIsOpen((c) => !c)}
      >
        <span className="truncate pr-3">{selectedLabel}</span>
        <span className="text-[0.75rem]" aria-hidden="true">
          {isOpen ? '−' : '+'}
        </span>
      </button>

      {isOpen ? (
        <div
          id={panelId}
          className="absolute left-0 top-full z-30 w-full min-w-[200px] border-2 border-t-0 border-ot-ink bg-ot-surface"
          role="listbox"
        >
          {options.map((option, index) => {
            const isSelected = option.value === value
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={[
                  'flex min-h-10 w-full items-center gap-3 bg-ot-surface px-3 py-2 text-left font-body text-[0.8125rem] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                  index === 0 ? '' : 'border-t-2 border-ot-line',
                  'hover:bg-ot-bg',
                ].join(' ')}
                onClick={() => {
                  onChange(option.value)
                  setIsOpen(false)
                }}
              >
                <span className="flex h-3.5 w-3.5 flex-none items-center justify-center border-2 border-ot-ink" aria-hidden="true">
                  {isSelected ? <span className="h-1.5 w-1.5 bg-ot-red" /> : null}
                </span>
                <span className="truncate">{option.label}</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
