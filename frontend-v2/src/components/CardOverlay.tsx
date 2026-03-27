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
    <aside className="card-overlay" aria-label="Card details">
      <div className="card-overlay-header">
        <div className="card-overlay-heading">
          <p className="eyebrow">Card Detail</p>
          <h2 className="card-overlay-title">{display.name}</h2>
        </div>
        <button type="button" onClick={onClose} className="card-overlay-close">
          Close
        </button>
      </div>

      <div className="card-overlay-meta">
        {display.manaCost ? (
          <span className="card-overlay-chip">
            <SymbolText text={display.manaCost} />
          </span>
        ) : null}
        {displayCard.set_code ? (
          <span className="card-overlay-chip">{displayCard.set_code.toUpperCase()}</span>
        ) : null}
        <span className="card-overlay-chip">{Math.round(card.similarity * 100)}% match</span>
      </div>

      <CardImage
        src={getCardImageUrl(card, 'large')}
        alt={display.name}
        className="card-overlay-image"
      />

      <div className="card-overlay-body">
        {display.typeLine ? (
          <p className="card-overlay-type">{display.typeLine}</p>
        ) : null}
        {display.oracleText ? (
          <p className="card-overlay-text">
            <SymbolText text={display.oracleText} />
          </p>
        ) : null}
        {hasStats ? (
          <p className="card-overlay-stats">
            {display.power}
            {' / '}
            {display.toughness}
          </p>
        ) : null}
        {isLoading ? <p className="card-overlay-loading">Loading fuller card text...</p> : null}
      </div>
    </aside>
  )
}
