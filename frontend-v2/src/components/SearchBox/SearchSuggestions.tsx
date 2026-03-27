import type { CardMatch } from '../../types/api'

interface SearchSuggestionsProps {
  items: CardMatch[]
  activeIndex: number
  isLoading: boolean
  onSelect: (card: CardMatch) => void
  onHover: (index: number) => void
}

export function SearchSuggestions({
  items,
  activeIndex,
  isLoading,
  onSelect,
  onHover,
}: SearchSuggestionsProps) {
  if (isLoading) {
    return (
      <div className="search-suggestions">
        <p className="eyebrow">Loading</p>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="search-suggestions">
        <p className="eyebrow">No Matches</p>
      </div>
    )
  }

  return (
    <div className="search-suggestions" role="listbox" aria-label="Card name suggestions">
      {items.map((item, index) => (
        <button
          key={`${item.oracle_id ?? item.name}-${item.face_ix}`}
          type="button"
          className={`suggestion-item ${activeIndex === index ? 'suggestion-item-active' : ''}`}
          onMouseEnter={() => onHover(index)}
          onClick={() => onSelect(item)}
        >
          <span className="suggestion-name">{item.name}</span>
          <span className="suggestion-meta">
            {item.oracle_id ? 'Card' : 'Name'}
          </span>
        </button>
      ))}
    </div>
  )
}
