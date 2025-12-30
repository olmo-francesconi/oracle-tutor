import type { Card, SimilarCard } from './types'

export function getCardImageUrl(card: Card | SimilarCard): string {
  let side = 'front'

  // Layouts that physically have a back side
  const doubleSidedLayouts = [
    'transform',
    'modal_dfc',
    'meld',
    'double_faced_token',
    'art_series',
  ]

  // If we know the layout, and it's NOT double-sided, force front
  // (This fixes Adventure/Split cards trying to load a back image)
  if (card.layout && !doubleSidedLayouts.includes(card.layout)) {
    side = 'front'
  } else {
    // Check if it's a SimilarCard with card_name (which comes from the API for search results)
    if ('card_name' in card && card.card_name) {
      // If the face name (card.name) is the second part of the full card name, it's the back face
      if (card.card_name.includes(' // ')) {
        const parts = card.card_name.split(' // ')
        if (parts.length > 1 && card.name === parts[1]) {
          side = 'back'
        }
      }
    }
  }

  const id = card.id
  if (!id || id.length < 2) return ''

  return `https://cards.scryfall.io/normal/${side}/${id[0]}/${id[1]}/${id}.jpg`
}
