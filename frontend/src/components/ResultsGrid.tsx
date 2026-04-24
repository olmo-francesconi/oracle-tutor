import { memo, useEffect, useRef } from 'react'
import { getCardImageUrl } from '../lib/cards'
import type { SimilarCard } from '../types/api'
import { CardImage } from './CardImage'

interface ResultsGridProps {
  cards: SimilarCard[]
  hasMore: boolean
  isLoadingMore: boolean
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
}

const ResultCard = memo(function ResultCard({ card }: ResultCardProps) {
  const title = getCardTitle(card)

  return (
    <article
      className="group grid gap-0 border-2 border-ot-ink bg-ot-surface p-0 text-left text-inherit transition-transform duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
      style={{ ['--result-card-frame' as string]: getCardFrameColor(card.border_color ?? undefined) }}
    >
      <span className="relative z-10 flex min-h-5 items-center justify-start bg-ot-surface px-[10px] pb-[9px] pt-2 text-[0.625rem] uppercase tracking-[0.12em]">
        <span className="text-ot-muted transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] group-hover:text-ot-red motion-reduce:transition-none">
          {formatSimilarity(card.similarity)}
        </span>
      </span>

      <span className="block border-t-2 border-ot-ink bg-[var(--result-card-frame)] p-0">
        <CardImage
          src={getCardImageUrl(card)}
          alt={title}
          oracleText={card.oracle_text ?? undefined}
          manaCost={card.mana_cost ?? undefined}
          className="block aspect-[63/88] w-full rounded-[4.8%/3.5%] border-0 bg-[#d8d2c8] object-cover"
        />
      </span>
    </article>
  )
})

export function ResultsGrid({
  cards,
  hasMore,
  isLoadingMore,
  onLoadMore,
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
      className="grid grid-cols-[repeat(auto-fill,minmax(164px,1fr))] gap-3 max-[720px]:grid-cols-[repeat(auto-fill,minmax(154px,1fr))]"
      aria-label="Search results"
      aria-busy={isLoadingMore}
    >
      {cards.map((card) => {
        return (
          <ResultCard
            key={getCardKey(card)}
            card={card}
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
          aria-hidden="true"
        >
          {isLoadingMore ? 'Loading more cards...' : 'Scroll for more'}
        </div>
      ) : null}
    </section>
  )
}
