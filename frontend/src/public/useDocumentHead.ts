import { useEffect } from 'react'
import { applyDocumentHead, getAppOrigin } from '../lib/documentHead'
import { buildCanonicalUrl } from '../lib/urlState'
import { getCardImageUrl } from '../lib/cards'
import type { Card, FilterState } from '../types/api'
import type { PinnedCard } from '../types/ui'

const SITE_NAME = 'Oracle Tutor'
const DEFAULT_DESCRIPTION =
  'Oracle Tutor is a semantic search engine for Magic: The Gathering. Describe what a card does and find every card that matches, by meaning rather than exact name.'

type Args = {
  isHome: boolean
  submittedQuery: string | null
  pinnedCard: PinnedCard | null
  pinnedCardData: Card | null
  filters: FilterState
}

function truncate(text: string, max = 200): string {
  const collapsed = text.replace(/\s+/g, ' ').trim()
  if (collapsed.length <= max) return collapsed
  return `${collapsed.slice(0, max - 1).trimEnd()}…`
}

export function useDocumentHead({
  isHome,
  submittedQuery,
  pinnedCard,
  pinnedCardData,
  filters,
}: Args): void {
  useEffect(() => {
    const origin = getAppOrigin()

    if (isHome) {
      applyDocumentHead({
        title: SITE_NAME,
        description: DEFAULT_DESCRIPTION,
        canonical: buildCanonicalUrl(origin, null, null),
      })
      return
    }

    if (pinnedCard) {
      const card = pinnedCardData
      const face = card?.faces?.[pinnedCard.face_ix] ?? card?.faces?.[0] ?? null
      const cardName = card?.name ?? pinnedCard.name
      const oracleText = card?.oracle_text ?? face?.oracle_text ?? null
      const typeLine = card?.type_line ?? face?.type_line ?? null

      const description = oracleText
        ? truncate(`${typeLine ? `${typeLine}. ` : ''}${oracleText}`)
        : `Cards similar to ${cardName} on ${SITE_NAME}.`

      applyDocumentHead({
        title: cardName ? `${cardName} | ${SITE_NAME}` : `Card detail | ${SITE_NAME}`,
        description,
        canonical: buildCanonicalUrl(origin, null, pinnedCard),
        ogImage: card ? getCardImageUrl({ ...card, image_side: 'front' }, 'normal') : null,
        ogType: 'article',
      })
      return
    }

    if (submittedQuery) {
      applyDocumentHead({
        title: `"${submittedQuery}" | ${SITE_NAME}`,
        description: `Magic: The Gathering cards matching "${submittedQuery}". Semantic search by meaning on ${SITE_NAME}.`,
        canonical: buildCanonicalUrl(origin, submittedQuery, null),
        // Filtered result pages are not indexed: filter permutations would
        // explode duplicate content. The canonical points at the unfiltered
        // version of the query above; this also signals the bot.
        robots: hasActiveFilters(filters) ? 'noindex,follow' : 'index,follow',
      })
      return
    }

    applyDocumentHead({
      title: SITE_NAME,
      description: DEFAULT_DESCRIPTION,
      canonical: buildCanonicalUrl(origin, null, null),
    })
  }, [isHome, submittedQuery, pinnedCard, pinnedCardData, filters])
}

function hasActiveFilters(filters: FilterState): boolean {
  return (
    Boolean(filters.colors) ||
    Boolean(filters.cardType?.length) ||
    Boolean(filters.format?.length) ||
    filters.cmcMin !== undefined ||
    filters.cmcMax !== undefined ||
    Boolean(filters.rarities?.length) ||
    Boolean(filters.matchMode) ||
    Boolean(filters.colorFeature)
  )
}
