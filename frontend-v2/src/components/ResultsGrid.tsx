import { memo, useEffect, useRef } from 'react'
import { getCardImageUrl } from '../lib/cards'
import type { SimilarCard } from '../types/api'
import { CardImage } from './CardImage'

interface ResultsGridProps {
  cards: SimilarCard[]
  hasMore: boolean
  isLoadingMore: boolean
  selectedCardKey: string | null
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

function getCardKey(card: SimilarCard): string {
  return `${card.id}-${card.face_ix}-${card.image_side}`
}

interface ResultCardProps {
  card: SimilarCard
  isSelected: boolean
  onCardSelect: (card: SimilarCard) => void
}

const ResultCard = memo(function ResultCard({ card, isSelected, onCardSelect }: ResultCardProps) {
  const title = getCardTitle(card)

  return (
    <button
      type="button"
      className={[
        'group grid gap-0 border-2 border-ot-ink bg-ot-surface p-0 text-left text-inherit transition-[transform,background-color,color] duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:-translate-y-0.5 hover:bg-transparent motion-reduce:transition-none motion-reduce:hover:translate-y-0',
        isSelected ? 'bg-transparent text-ot-ink' : '',
      ].join(' ')}
      aria-pressed={isSelected}
      onClick={() => onCardSelect(card)}
      style={{ ['--result-card-frame' as string]: getCardFrameColor(card.border_color) }}
    >
      <span className="flex min-h-5 items-center justify-start px-[10px] pb-[9px] pt-2 text-[0.625rem] uppercase tracking-[0.12em]">
        <span
          className={[
            'text-ot-muted transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
            isSelected ? 'text-ot-red' : 'group-hover:text-ot-red',
          ].join(' ')}
        >
          {formatSimilarity(card.similarity)}
        </span>
      </span>

      <span className="block border-t-2 border-ot-ink bg-[var(--result-card-frame)] p-0">
        <CardImage
          src={getCardImageUrl(card)}
          alt={title}
          className="block aspect-[63/88] w-full rounded-[4.8%/3.5%] border-0 bg-[#d8d2c8] object-cover"
        />
      </span>
    </button>
  )
})

export function ResultsGrid({
  cards,
  hasMore,
  isLoadingMore,
  selectedCardKey,
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
    <section
      className="grid grid-cols-[repeat(auto-fill,minmax(164px,1fr))] gap-3 max-[720px]:grid-cols-[repeat(auto-fill,minmax(154px,1fr))]"
      aria-label="Search results"
    >
      {cards.map((card) => {
        const cardKey = getCardKey(card)

        return (
          <ResultCard
            key={cardKey}
            card={card}
            isSelected={selectedCardKey === cardKey}
            onCardSelect={onCardSelect}
          />
        )
      })}

      {hasMore ? (
        <div
          ref={sentinelRef}
          className="col-[1/-1] border-t-2 border-ot-ink pt-3 text-left text-xs uppercase tracking-[0.11em] text-ot-muted"
          aria-hidden="true"
        >
          {isLoadingMore ? 'Loading more cards...' : 'Scroll for more'}
        </div>
      ) : null}
    </section>
  )
}
