import type { Card, SimilarCard } from './types'

export type CardImageSize = 'small' | 'normal' | 'large'
const DOUBLE_SIDED_LAYOUTS = new Set([
  'transform',
  'modal_dfc',
  'meld',
  'double_faced_token',
  'art_series',
])

type CardImageLike = Pick<Card, 'id'> &
  Partial<Pick<Card, 'layout' | 'name' | 'scryfall_id' | 'faces'>> &
  Partial<Pick<SimilarCard, 'card_name' | 'image_side'>>

type CardImageSource =
  | Card
  | SimilarCard
  | (CardImageLike & { image_side?: 'front' | 'back' })

export function getCardImageUrl(
  card: CardImageSource,
  size: CardImageSize = 'normal'
): string {
  if ('faces' in card && Array.isArray(card.faces) && card.faces.length > 0) {
    const faceIndex =
      'image_side' in card && card.image_side === 'back' && card.faces.length > 1
        ? 1
        : 0
    const face = card.faces[faceIndex] ?? card.faces[0]
    if (face?.image_uris?.[size]) {
      return face.image_uris[size]
    }
  }

  const side = 'image_side' in card && card.image_side ? card.image_side : 'front'

  const id = card.scryfall_id ?? card.id
  if (!id || id.length < 2) return ''

  return `https://cards.scryfall.io/${size}/${side}/${id[0]}/${id[1]}/${id}.jpg`
}

export function getImageSideForFace(
  layout: string | undefined,
  faceIx: number
): 'front' | 'back' {
  if (layout && DOUBLE_SIDED_LAYOUTS.has(layout) && faceIx > 0) {
    return 'back'
  }
  return 'front'
}
