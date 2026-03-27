import { useEffect, useMemo, useState } from 'react'
import { getCard } from '../lib/api'
import { getDisplayFace, getCardImageUrl } from '../lib/cards'
import type { Card, SimilarCard } from '../types/api'
import { CardImage } from './CardImage'
import { SymbolText } from './SymbolText'

interface CardOverlayProps {
  card: SimilarCard
  onClose: () => void
}

function needsDetailFetch(card: SimilarCard): boolean {
  return !card.oracle_text || !card.type_line || !card.mana_cost
}

function getDisplayData(card: Card | SimilarCard) {
  const face = getDisplayFace(card)
  const cardName = 'card_name' in card ? card.card_name : undefined

  return {
    name: face?.name ?? cardName ?? card.name,
    manaCost: face?.mana_cost ?? card.mana_cost,
    typeLine: face?.type_line ?? card.type_line,
    oracleText: face?.oracle_text ?? card.oracle_text,
    power: face?.power ?? card.power,
    toughness: face?.toughness ?? card.toughness,
  }
}

export function CardOverlay({ card, onClose }: CardOverlayProps) {
  const [detailCard, setDetailCard] = useState<Card | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    setDetailCard(null)

    if (!needsDetailFetch(card)) return

    const controller = new AbortController()

    void (async () => {
      setIsLoading(true)

      try {
        const nextCard = await getCard(card.id, controller.signal)
        if (!controller.signal.aborted) {
          setDetailCard(nextCard)
        }
      } catch {
        if (!controller.signal.aborted) {
          setDetailCard(null)
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    })()

    return () => controller.abort()
  }, [card])

  const displayCard = detailCard ?? card
  const display = useMemo(() => getDisplayData(displayCard), [displayCard])
  const hasStats = display.power && display.toughness

  return (
    <aside
      className="sticky top-24 grid gap-4 border-2 border-ot-ink bg-ot-surface p-4 animate-ot-fade-slide-in max-[900px]:static"
      aria-label="Card details"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1.5">
          <p className="eyebrow">Detail Rail</p>
          <h2 className="font-display text-[clamp(2.1rem,4vw,2.65rem)] font-black uppercase leading-[0.9] tracking-[-0.02em]">
            {display.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="cursor-pointer border-2 border-ot-ink bg-transparent px-[10px] py-2 uppercase tracking-[0.08em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
        >
          Close
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {display.manaCost ? (
          <span className="border-2 border-ot-ink bg-ot-bg px-2 py-1.5 text-[0.6875rem] font-medium uppercase leading-none tracking-[0.12em]">
            <SymbolText text={display.manaCost} />
          </span>
        ) : null}
        {displayCard.set_code ? (
          <span className="border-2 border-ot-ink bg-ot-bg px-2 py-1.5 text-[0.6875rem] font-medium uppercase leading-none tracking-[0.12em]">
            {displayCard.set_code.toUpperCase()}
          </span>
        ) : null}
        <span className="border-2 border-ot-ink bg-ot-bg px-2 py-1.5 text-[0.6875rem] font-medium uppercase leading-none tracking-[0.12em]">
          {Math.round(card.similarity * 100)}% match
        </span>
      </div>

      <CardImage
        src={getCardImageUrl(card, 'large')}
        alt={display.name}
        className="aspect-[63/88] w-full border-2 border-ot-ink bg-[#d8d2c8] object-cover"
      />

      <div className="grid gap-3">
        {display.typeLine ? (
          <p className="m-0 text-xs uppercase tracking-[0.08em] text-ot-muted">{display.typeLine}</p>
        ) : null}
        {display.oracleText ? (
          <p className="m-0 text-sm leading-[1.65]" aria-label="Oracle text">
            <SymbolText text={display.oracleText} />
          </p>
        ) : null}
        {hasStats ? (
          <p className="m-0 text-[0.8125rem] uppercase tracking-[0.12em] text-ot-ink" aria-label="Power and toughness">
            {display.power}
            {' / '}
            {display.toughness}
          </p>
        ) : null}
        {isLoading ? <p className="m-0 text-sm leading-[1.65] text-ot-muted">Loading fuller card text...</p> : null}
      </div>
    </aside>
  )
}
