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

const BORDER_COLOR_MAP: Record<string, string> = {
  black: '#111111',
  white: '#ededef',
  silver: '#8a8a8a',
  gold: '#a8894d',
  borderless: '#111111',
}

function getCardFrameColor(borderColor: string | undefined): string {
  return (borderColor && BORDER_COLOR_MAP[borderColor]) ?? '#111111'
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
            style={{ ['--result-card-frame' as string]: getCardFrameColor(card.border_color) }}
          >
            <span className="result-card-footer">
              <span className="result-card-similarity">{formatSimilarity(card.similarity)}</span>
            </span>

            <span className="result-card-frame">
              <CardImage
                src={getCardImageUrl(card)}
                alt={title}
                className="result-card-image"
              />
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
