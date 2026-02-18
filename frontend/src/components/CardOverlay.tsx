import { ArrowsClockwise, MagnifyingGlass, X } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCard } from '../api'
import { cn } from '../lib/cn'
import type { SimilarCard } from '../types'
import { getCardImageUrl } from '../utils'
import { CardImage } from './CardImage'
import { SymbolText } from './SymbolText'

interface CardOverlayProps {
  card: SimilarCard
  onClose: () => void
}

export function CardOverlay({ card: initialCard, onClose }: CardOverlayProps) {
  const [userFaceIndex, setUserFaceIndex] = useState<number | null>(null)
  const [isFlipping, setIsFlipping] = useState(false)

  // Fetch the full card details to get faces and correct full name
  const { data: fullCard, isSuccess } = useQuery({
    queryKey: ['card', initialCard.id],
    queryFn: () => getCard(initialCard.id),
    enabled: !!initialCard.id,
    staleTime: 1000 * 60 * 60, // Cache for 1 hour
  })

  const initialFaceIndex = useMemo(() => {
    if (!isSuccess || !fullCard) return 0
    if (fullCard.faces && fullCard.faces.length > 0) {
      const matchingIndex = fullCard.faces.findIndex(
        (f) => f.name === initialCard.name
      )
      return matchingIndex !== -1 ? matchingIndex : 0
    }
    return 0
  }, [isSuccess, fullCard, initialCard.name])

  // Lock body scroll when overlay is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [])

  const doubleSidedLayouts = [
    'transform',
    'modal_dfc',
    'meld',
    'double_faced_token',
    'art_series',
  ]
  const isDoubleSided = fullCard?.layout
    ? doubleSidedLayouts.includes(fullCard.layout)
    : false

  // Logic for Shared Face cards (Split, Adventure, Flip)
  // These have multiple faces but exist on one physical side.
  // We want to combine their stats into one view.
  const isSharedFace =
    fullCard?.faces && fullCard.faces.length > 1 && !isDoubleSided

  const hasMultipleFaces =
    fullCard?.faces && fullCard.faces.length > 1 && isDoubleSided
  const currentFaceIdx = userFaceIndex ?? initialFaceIndex

  // Resolve displayed data
  let displayData = initialCard

  if (fullCard) {
    if (isSharedFace && fullCard.faces) {
      // Combine Data for Shared Face Cards
      displayData = {
        ...fullCard.faces[0], // Base props from first face
        id: fullCard.id,
        name: fullCard.name, // Use full joined name
        type_line: fullCard.faces.map((f) => f.type_line).join(' // '),
        mana_cost: fullCard.faces.map((f) => f.mana_cost || '').join(' // '),
        // Join oracle text with a separator
        oracle_text: fullCard.faces
          .map((f) => f.oracle_text)
          .filter(Boolean)
          .join('\n\n'),
        similarity: initialCard.similarity,
      }
    } else if (fullCard.faces && fullCard.faces[currentFaceIdx]) {
      // Standard Single or Double Sided view
      displayData = {
        ...fullCard.faces[currentFaceIdx],
        id: fullCard.id,
        similarity: initialCard.similarity,
      }
    }
  }

  // Construct Image URL dynamically
  let imageUrl = ''
  if (hasMultipleFaces) {
    const side = currentFaceIdx === 0 ? 'front' : 'back'
    const id = fullCard.id
    imageUrl = `https://cards.scryfall.io/normal/${side}/${id[0]}/${id[1]}/${id}.jpg`
  } else {
    imageUrl = getCardImageUrl(initialCard)
  }

  const handleFlip = () => {
    if (hasMultipleFaces && !isFlipping) {
      setIsFlipping(true)
      setTimeout(() => {
        setUserFaceIndex((prev) => ((prev ?? currentFaceIdx) === 0 ? 1 : 0))
      }, 125)
      setTimeout(() => {
        setIsFlipping(false)
      }, 250)
    }
  }

  // Display Name: prefer full card name (A // B)
  const displayName =
    fullCard?.name || initialCard.card_name || initialCard.name

  // External URLs
  const cardSlug = displayName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
  const encodedName = encodeURIComponent(displayName)
  const scryfallUrl = `https://scryfall.com/card/${initialCard.id}`
  const edhrecUrl = `https://edhrec.com/cards/${cardSlug}`
  const moxfieldUrl = `https://www.moxfield.com/search/cards?q=${encodedName}`

  return (
    <div className="fixed inset-0 z-[100] flex animate-[fadeIn_0.2s_ease-out] items-center justify-center p-4 sm:p-8">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Content - Fixed height to prevent resizing on flip */}
      <div className="relative flex max-h-[90vh] w-full max-w-4xl animate-[slideUp_0.3s_ease-out] flex-col overflow-y-auto rounded-2xl bg-[#f5f2eb] shadow-2xl md:h-[750px] md:max-h-none md:flex-row md:overflow-hidden">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-10 rounded-full bg-[#1c1c1c]/80 p-2.5 text-white shadow-lg ring-1 ring-black/20 backdrop-blur-sm transition-all hover:scale-105 hover:bg-[#1c1c1c] focus-visible:ring-2 focus-visible:ring-[#e3dccb] focus-visible:outline-none"
          aria-label="Close"
        >
          <X className="h-6 w-6" weight="bold" />
        </button>

        {/* Image Section */}
        <div className="relative flex w-full items-center justify-center bg-[#e5e5e5] p-4 sm:p-8 md:w-1/2 md:overflow-y-auto">
          {/* Wrapper: size to viewport on mobile; fixed aspect box on desktop */}
          <div className="group relative inline-block overflow-hidden rounded-[4.5%/3.21%] shadow-2xl ring-1 ring-black/10 md:aspect-[5/7] md:w-full md:max-w-[360px]">
            {/* Rotating Card Container */}
            <div
              onClick={hasMultipleFaces ? handleFlip : undefined}
              className={cn(
                'h-full w-full shrink-0 transition-all duration-[250ms] ease-in-out',
                hasMultipleFaces && 'cursor-pointer'
              )}
              style={{
                transform: isFlipping ? 'rotateY(90deg)' : 'rotateY(0deg)',
                opacity: isFlipping ? 0.5 : 1,
              }}
            >
              {/* Card Image */}
              <CardImage
                src={imageUrl}
                alt={displayData.name}
                className="block max-h-[55vh] w-auto max-w-full object-contain md:h-full md:max-h-none md:w-full"
              />

              {/* Flip Symbol (Top Right) */}
              {hasMultipleFaces && (
                <div className="absolute top-4 right-4 z-20 opacity-0 transition-all duration-300 group-hover:opacity-100">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleFlip()
                    }}
                    className="rounded-full bg-black/60 p-3 text-white shadow-lg backdrop-blur-sm transition-all hover:scale-110 hover:bg-black/80"
                  >
                    <ArrowsClockwise className="h-5 w-5" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Details Section */}
        <div className="flex w-full flex-col bg-white p-5 text-[#1c1c1c] sm:p-8 md:w-1/2 md:overflow-y-auto md:p-10">
          <div className="flex-1">
            <h2 className="mb-2 text-2xl font-bold text-[#1c1c1c] sm:text-3xl">
              {displayName}
            </h2>

            <div className="mb-5 flex items-center gap-3 text-[#737373] sm:mb-6">
              {initialCard.similarity !== undefined && (
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 text-xs font-bold text-white',
                    initialCard.similarity > 0.8
                      ? 'bg-emerald-500'
                      : 'bg-amber-500'
                  )}
                >
                  {(initialCard.similarity * 100).toFixed(1)}% Match
                </span>
              )}
            </div>

            {/* Animated Details Container */}
            <div
              className={cn(
                'space-y-5 transition-opacity duration-[125ms] ease-in-out sm:space-y-6',
                isFlipping ? 'opacity-0' : 'opacity-100'
              )}
            >
              <p className="text-base leading-snug font-medium text-[#404040] sm:text-lg">
                <span className="text-[#1c1c1c]">
                  {displayData.type_line || '—'}
                </span>{' '}
                <span className="px-1.5 text-[#a3a3a3]" aria-hidden="true">
                  •
                </span>
                <span className="text-[#1c1c1c]">
                  <SymbolText text={displayData.mana_cost || 'None'} />
                </span>
              </p>

              <div className="border-t border-[#f5f5f5] pt-5 sm:pt-6">
                <span className="mb-2 block text-xs font-semibold tracking-wider text-[#a3a3a3] uppercase">
                  Oracle Text
                </span>

                {isSharedFace && fullCard?.faces ? (
                  <div className="flex flex-col">
                    {fullCard.faces.map((face, idx) => (
                      <div
                        key={idx}
                        className={
                          idx > 0 ? 'mt-6 border-t border-[#f5f5f5] pt-6' : ''
                        }
                      >
                        <p className="text-sm leading-relaxed whitespace-pre-wrap text-[#404040]">
                          <SymbolText
                            text={face.oracle_text || 'No oracle text.'}
                          />
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm leading-relaxed whitespace-pre-wrap text-[#404040]">
                    <SymbolText
                      text={displayData.oracle_text || 'No oracle text.'}
                    />
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Footer: External Links + Action Button */}
          <div className="mt-8">
            {/* External Links - Centered, no top border */}
            <div className="flex flex-col items-center pb-6">
              <span className="mb-3 block text-center text-xs font-semibold tracking-wider text-[#a3a3a3] uppercase">
                External Links
              </span>
              <div className="flex flex-wrap justify-center gap-2">
                <a
                  href={scryfallUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md bg-[#f5f5f5] px-3 py-1.5 text-xs font-semibold text-[#525252] transition-colors hover:bg-[#e5e5e5] hover:text-[#1c1c1c]"
                >
                  <img
                    src="https://www.google.com/s2/favicons?domain=scryfall.com&sz=32"
                    alt=""
                    className="h-4 w-4 rounded-sm opacity-80"
                  />
                  Scryfall
                </a>
                <a
                  href={edhrecUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md bg-[#f5f5f5] px-3 py-1.5 text-xs font-semibold text-[#525252] transition-colors hover:bg-[#e5e5e5] hover:text-[#1c1c1c]"
                >
                  <img
                    src="https://www.google.com/s2/favicons?domain=edhrec.com&sz=32"
                    alt=""
                    className="h-4 w-4 rounded-sm opacity-80"
                  />
                  EDHREC
                </a>
                <a
                  href={moxfieldUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md bg-[#f5f5f5] px-3 py-1.5 text-xs font-semibold text-[#525252] transition-colors hover:bg-[#e5e5e5] hover:text-[#1c1c1c]"
                >
                  <img
                    src="https://www.google.com/s2/favicons?domain=moxfield.com&sz=32"
                    alt=""
                    className="h-4 w-4 rounded-sm opacity-80"
                  />
                  Moxfield
                </a>
              </div>
            </div>

            {/* Action Button - Separator moved here */}
            <div className="border-t border-[#f5f5f5] pt-6">
              <Link
                to={`/card/${initialCard.id}`}
                onClick={onClose}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#1c1c1c] px-6 py-3 font-semibold text-white shadow-lg transition-all hover:bg-[#333] hover:shadow-xl active:scale-[0.98]"
              >
                <MagnifyingGlass className="h-4 w-4" />
                Find Similar Cards
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
