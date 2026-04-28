import type { CardMatch } from '../../types/api'

interface SearchSuggestionsProps {
  id: string
  variant: 'home' | 'topbar'
  items: CardMatch[]
  activeIndex: number
  onSelect: (card: CardMatch) => void
  onHover: (index: number) => void
}

export function SearchSuggestions({
  id,
  variant,
  items,
  activeIndex,
  onSelect,
  onHover,
}: SearchSuggestionsProps) {
  return (
    <div
      className={[
        'animate-ot-fade-slide-in origin-top border-2 border-t-0 border-ot-ink bg-ot-surface',
        variant === 'topbar'
          ? 'absolute inset-x-[-2px] top-full z-40 border-t-2'
          : 'absolute inset-x-0 top-full z-30',
      ].join(' ')}
      id={id}
      role="listbox"
      aria-label="Card name suggestions"
    >
      {items.map((item, index) => {
        const showParent = !!item.card_name && item.card_name !== item.name
        const isActive = activeIndex === index
        return (
          <button
            id={`${id}-option-${index}`}
            key={`${item.oracle_id ?? item.name}-${item.face_ix}`}
            type="button"
            role="option"
            aria-selected={isActive}
            className="relative flex w-full items-center justify-between gap-3 border-0 border-b-2 border-ot-line bg-ot-surface px-[14px] py-3 text-left text-ot-ink last:border-b-0"
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => onHover(index)}
            onClick={() => onSelect(item)}
          >
            <span
              aria-hidden="true"
              className={[
                'pointer-events-none absolute inset-y-0 left-0 w-1 bg-ot-red transition-opacity duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                isActive ? 'opacity-100' : 'opacity-0',
              ].join(' ')}
            />
            <span className={['min-w-0 truncate transition-transform duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none motion-reduce:transform-none', isActive ? 'translate-x-1' : ''].join(' ')}>
              <span>{item.name}</span>
              {showParent ? (
                <span className="ml-2 text-ot-muted">({item.card_name})</span>
              ) : null}
            </span>
            <span
              className={[
                'shrink-0 text-[0.6875rem] uppercase tracking-[0.12em] text-ot-muted transition-transform duration-120 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none motion-reduce:transform-none',
                isActive ? 'translate-x-1' : '',
              ].join(' ')}
            >
              {item.oracle_id ? 'Card' : 'Name'}
            </span>
          </button>
        )
      })}
    </div>
  )
}
