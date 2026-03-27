import { useEffect, useRef } from 'react'
import { getCardImageUrl } from '../lib/cards'
import type { SimilarCard } from '../types/api'
import { CardImage } from './CardImage'

interface ResultsGridProps {
  cards: SimilarCard[]
  hasMore: boolean
  isLoadingMore: boolean
  selectedCardId: string | null
  onCardSelect: (card: SimilarCard) => void
  onLoadMore: () => void
}

function formatSimilarity(similarity: number): string {
  return `${Math.round(similarity * 100)}%`
}

function getCardTitle(card: SimilarCard): string {
  return card.card_name || card.name
}

function getCardSubtitle(card: SimilarCard): string {
  return card.type_line || 'Card'
}

function getCardExcerpt(card: SimilarCard): string {
  if (!card.oracle_text) return 'Oracle text unavailable.'

  return card.oracle_text.length > 156
    ? `${card.oracle_text.slice(0, 153).trimEnd()}...`
    : card.oracle_text
}

export function ResultsGrid({
  cards,
  hasMore,
  isLoadingMore,
  selectedCardId,
  onCardSelect,
  onLoadMore,
}: ResultsGridProps) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hasMore || isLoadingMore || !sentinelRef.current) return

    const observer = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) return
      onLoadMore()
    })

    observer.observe(sentinelRef.current)

    return () => observer.disconnect()
  }, [hasMore, isLoadingMore, onLoadMore])

  return (
    <section className="results-grid" aria-label="Search results">
      {cards.map((card) => {
        const title = getCardTitle(card)

        return (
          <button
            key={`${card.id}-${card.face_ix}-${card.image_side}`}
            type="button"
            className={`result-card ${selectedCardId === card.id ? 'result-card-active' : ''}`}
            aria-pressed={selectedCardId === card.id}
            onClick={() => onCardSelect(card)}
          >
            <CardImage
              src={getCardImageUrl(card)}
              alt={title}
              className="result-card-image"
            />

            <span className="result-card-body">
              <span className="result-card-meta">
                <span className="result-card-similarity">{formatSimilarity(card.similarity)}</span>
                {card.set_code ? (
                  <span className="result-card-set">{card.set_code.toUpperCase()}</span>
                ) : null}
              </span>
              <span className="result-card-title">{title}</span>
              <span className="result-card-subtitle">{getCardSubtitle(card)}</span>
              <span className="result-card-text">{getCardExcerpt(card)}</span>
            </span>
          </button>
        )
      })}

      {hasMore ? (
        <div ref={sentinelRef} className="results-sentinel" aria-hidden="true">
          {isLoadingMore ? 'Loading more cards...' : 'Scroll for more'}
        </div>
      ) : null}
    </section>
  )
}
