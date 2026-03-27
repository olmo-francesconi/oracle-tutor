import type { Card, SimilarCard } from '../types/api'

export type CardImageSize = 'small' | 'normal' | 'large'

type CardImageLike = Pick<Card, 'id'> &
  Partial<Pick<Card, 'scryfall_id' | 'faces'>> &
  Partial<Pick<SimilarCard, 'image_side'>>

export function getCardImageUrl(
  card: CardImageLike,
  size: CardImageSize = 'normal'
): string {
  if (Array.isArray(card.faces) && card.faces.length > 0) {
    const faceIndex = card.image_side === 'back' && card.faces.length > 1 ? 1 : 0
    const face = card.faces[faceIndex] ?? card.faces[0]

    if (face?.image_uris?.[size]) {
      return face.image_uris[size]
    }
  }

  const id = card.scryfall_id ?? card.id
  if (!id || id.length < 2) return ''

  const side = card.image_side ?? 'front'
  return `https://cards.scryfall.io/${size}/${side}/${id[0]}/${id[1]}/${id}.jpg`
}
