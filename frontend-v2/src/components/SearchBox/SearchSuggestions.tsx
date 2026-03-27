import type { CardMatch } from '../../types/api'

interface SearchSuggestionsProps {
  variant: 'home' | 'topbar'
  items: CardMatch[]
  activeIndex: number
  isLoading: boolean
  onSelect: (card: CardMatch) => void
  onHover: (index: number) => void
}

export function SearchSuggestions({
  variant,
  items,
  activeIndex,
  isLoading,
  onSelect,
  onHover,
}: SearchSuggestionsProps) {
  if (isLoading) {
    return (
      <div
        className={[
          'animate-ot-fade-slide-in origin-top border-2 border-t-0 border-ot-ink bg-ot-surface',
          variant === 'topbar'
            ? 'absolute inset-x-[-2px] top-full z-40 border-t-2'
            : 'absolute inset-x-0 top-full z-30',
        ].join(' ')}
      >
        <div className="grid gap-2 px-[14px] pb-0 pt-[14px]" aria-hidden="true">
          <span className="block h-2 w-[58%] animate-ot-loading-pulse bg-[color-mix(in_srgb,var(--color-ot-line)_80%,var(--color-ot-bg))] opacity-70" />
          <span className="block h-2 w-[24%] animate-ot-loading-pulse bg-[color-mix(in_srgb,var(--color-ot-line)_80%,var(--color-ot-bg))] opacity-70" />
          <span className="block h-2 w-[58%] animate-ot-loading-pulse bg-[color-mix(in_srgb,var(--color-ot-line)_80%,var(--color-ot-bg))] opacity-70" />
        </div>
        <p className="m-0 px-[14px] pb-[14px] pt-[10px] text-[0.6875rem] uppercase tracking-[0.12em] text-ot-muted">
          Loading card names...
        </p>
      </div>
    )
  }

  if (items.length === 0) {
    return null
  }

  return (
    <div
      className={[
        'animate-ot-fade-slide-in origin-top border-2 border-t-0 border-ot-ink bg-ot-surface',
        variant === 'topbar'
          ? 'absolute inset-x-[-2px] top-full z-40 border-t-2'
          : 'absolute inset-x-0 top-full z-30',
      ].join(' ')}
      role="listbox"
      aria-label="Card name suggestions"
    >
      {items.map((item, index) => (
        <button
          key={`${item.oracle_id ?? item.name}-${item.face_ix}`}
          type="button"
          className={[
            'flex w-full items-center justify-between gap-3 border-0 border-b-2 border-ot-line bg-ot-surface px-[14px] py-3 text-left text-ot-ink transition-[background-color,color] duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] last:border-b-0 motion-reduce:transition-none',
            activeIndex === index ? 'bg-ot-ink text-ot-bg' : '',
          ].join(' ')}
          onMouseEnter={() => onHover(index)}
          onClick={() => onSelect(item)}
        >
          <span className={activeIndex === index ? 'min-w-0 translate-x-0.5 transition-transform duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none motion-reduce:transform-none' : 'min-w-0 transition-transform duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none motion-reduce:transform-none'}>
            {item.name}
          </span>
          <span
            className={[
              'text-[0.6875rem] uppercase tracking-[0.12em] transition-[color,transform] duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none motion-reduce:transform-none',
              activeIndex === index ? 'translate-x-0.5 text-ot-bg' : 'text-ot-muted',
            ].join(' ')}
          >
            {item.oracle_id ? 'Card' : 'Name'}
          </span>
        </button>
      ))}
    </div>
  )
}
