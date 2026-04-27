import { memo, useEffect, useRef, useState } from 'react'
import { getCardImageUrl } from '../lib/cards'
import type { SimilarCard } from '../types/api'
import { CardImage } from './CardImage'

interface ResultsGridProps {
  cards: SimilarCard[]
  hasMore: boolean
  isLoadingMore: boolean
  onLoadMore: () => void
  onCardOpen: (card: SimilarCard) => void
}

function formatSimilarity(similarity: number): string {
  return `${Math.round(similarity * 100)}%`
}

function getCardTitle(card: SimilarCard): string {
  return card.card_name || card.name
}

function getCardKey(card: SimilarCard): string {
  return `${card.id}-${card.face_ix}-${card.image_side}`
}

interface ResultCardProps {
  card: SimilarCard
  onOpen: (card: SimilarCard) => void
}

const ResultCard = memo(function ResultCard({ card, onOpen }: ResultCardProps) {
  const title = getCardTitle(card)
  const [isImageLoaded, setIsImageLoaded] = useState(false)

  return (
    <article className="group flex flex-col gap-2 text-left text-inherit">
      <button
        type="button"
        onClick={() => onOpen(card)}
        aria-label={`Open detail for ${title}`}
        className="block w-full cursor-pointer border-0 bg-transparent p-0 text-inherit focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ot-red focus-visible:ring-offset-2 focus-visible:ring-offset-ot-bg"
      >
        <CardImage
          src={getCardImageUrl(card)}
          alt={title}
          oracleText={card.oracle_text ?? undefined}
          manaCost={card.mana_cost ?? undefined}
          className="block aspect-[63/88] w-full rounded-xl object-cover"
          onLoad={() => setIsImageLoaded(true)}
        />
      </button>
      <span
        className={[
          'px-1 text-[0.625rem] uppercase tracking-[0.12em] text-ot-muted transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] group-hover:text-ot-red motion-reduce:transition-none',
          isImageLoaded ? 'opacity-100' : 'opacity-0',
        ].join(' ')}
      >
        {formatSimilarity(card.similarity)}
      </span>
    </article>
  )
})

export function ResultsGrid({
  cards,
  hasMore,
  isLoadingMore,
  onLoadMore,
  onCardOpen,
}: ResultsGridProps) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const onLoadMoreRef = useRef(onLoadMore)

  useEffect(() => {
    onLoadMoreRef.current = onLoadMore
  }, [onLoadMore])

  useEffect(() => {
    if (!hasMore || isLoadingMore || !sentinelRef.current) return

    const observer = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) return
      onLoadMoreRef.current()
    })

    observer.observe(sentinelRef.current)

    return () => observer.disconnect()
  }, [hasMore, isLoadingMore])

  return (
    <section
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 min-[1500px]:grid-cols-6"
      aria-label="Search results"
      aria-busy={isLoadingMore}
    >
      {cards.map((card) => {
        return (
          <ResultCard
            key={getCardKey(card)}
            card={card}
            onOpen={onCardOpen}
          />
        )
      })}

      {hasMore ? (
        <div
          ref={sentinelRef}
          className={[
            'col-[1/-1] border-t-2 border-ot-ink pt-3 text-left text-xs uppercase tracking-[0.11em] text-ot-muted transition-opacity duration-150',
            isLoadingMore ? 'pointer-events-none opacity-55' : 'opacity-100',
          ].join(' ')}
          role="status"
          aria-live="polite"
        >
          {isLoadingMore ? 'Loading more cards...' : 'Scroll for more'}
        </div>
      ) : null}
    </section>
  )
}
