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

// Alpha printings (set code "lea") have a visibly wider corner radius than
// every later set; everything else uses the modern default.
// Card images have an aspect ratio of 63:88, so to produce *circular* (not
// elliptical) corners when scaling with width we set the vertical radius to
// `R × 63/88` of height. 7% / 5.011% resolves to equal x/y pixel radii.
export function getCardCornerRadiusClass(setCode?: string | null): string {
  return setCode === 'lea' ? 'rounded-[7%_/_5.011%]' : 'rounded-xl'
}

export function getDisplayFace(card: Card | SimilarCard) {
  if (!Array.isArray(card.faces) || card.faces.length === 0) {
    return null
  }

  const faceIndex =
    'image_side' in card && card.image_side === 'back' && card.faces.length > 1 ? 1 : 0

  return card.faces[faceIndex] ?? card.faces[0]
}
