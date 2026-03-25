import {
  ArrowsClockwiseIcon,
  CaretLeftIcon,
  CaretRightIcon,
  MagnifyingGlassIcon,
  XIcon,
} from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCard } from '../api'
import { cn } from '../lib/cn'
import type { SimilarCard } from '../types'
import { getCardImageUrl, getCardBorderColor, getCardRadiusStyle } from '../utils'
import { CardImage } from './CardImage'
import { SymbolText } from './SymbolText'

interface CardOverlayProps {
  card: SimilarCard
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
  hasPrev?: boolean
  hasNext?: boolean
}

export function CardOverlay({
  card: initialCard,
  onClose,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
}: CardOverlayProps) {
  const [userFaceIndex, setUserFaceIndex] = useState<number | null>(null)
  const [isFlipping, setIsFlipping] = useState(false)
  const [isImageLoaded, setIsImageLoaded] = useState(false)

  // Hide image when card changes; show when new image loads
  useEffect(() => {
    queueMicrotask(() => setIsImageLoaded(false))
  }, [initialCard.id, initialCard.face_ix])

  // Fetch the full card details to get faces and correct full name
  const { data: fullCard, isSuccess } = useQuery({
    queryKey: ['card', initialCard.oracle_id],
    queryFn: () => getCard(initialCard.oracle_id),
    enabled: !!initialCard.oracle_id,
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

  // Handle keyboard ArrowLeft/ArrowRight for navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && hasPrev && onPrev) {
        e.preventDefault()
        onPrev()
      } else if (e.key === 'ArrowRight' && hasNext && onNext) {
        e.preventDefault()
        onNext()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [hasPrev, hasNext, onPrev, onNext])

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
        scryfall_id: fullCard.scryfall_id,
        image_side: initialCard.image_side,
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
        scryfall_id: fullCard.scryfall_id,
        image_side: currentFaceIdx === 0 ? 'front' : 'back',
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
  const scryfallUrl = `https://scryfall.com/card/${initialCard.scryfall_id}`
  const edhrecUrl = `https://edhrec.com/cards/${cardSlug}`
  const moxfieldUrl = `https://www.moxfield.com/search/cards?q=${encodedName}`

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-8">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Prev/Next navigation - fixed on sides, above backdrop */}
      {hasPrev && onPrev && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onPrev()
          }}
          className="absolute top-1/2 left-2 z-[110] -translate-y-1/2 border-2 border-white bg-[#111111] p-3 text-white hover:bg-[#333] focus-visible:outline-none sm:left-4"
          aria-label="Previous card"
        >
          <CaretLeftIcon className="h-8 w-8 sm:h-10 sm:w-10" weight="bold" />
        </button>
      )}
      {hasNext && onNext && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onNext()
          }}
          className="absolute top-1/2 right-2 z-[110] -translate-y-1/2 border-2 border-white bg-[#111111] p-3 text-white hover:bg-[#333] focus-visible:outline-none sm:right-4"
          aria-label="Next card"
        >
          <CaretRightIcon className="h-8 w-8 sm:h-10 sm:w-10" weight="bold" />
        </button>
      )}

      {/* Modal Content */}
      <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-y-auto border-2 border-[#111111] bg-[#F0EDE6] md:h-[750px] md:max-h-none md:flex-row md:overflow-hidden">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 border-2 border-[#111111] bg-[#111111] p-2 text-white hover:bg-[#333] focus-visible:outline-none"
          aria-label="Close"
        >
          <XIcon className="h-5 w-5" weight="bold" />
        </button>

        {/* Image Section */}
        <div className="relative flex w-full flex-col items-center justify-center gap-4 bg-[#F0EDE6] p-6 md:w-1/2 md:overflow-y-auto md:p-8">
          {/* Card image wrapper */}
          <div
            className="relative inline-block overflow-hidden border-2 border-[#111111] transition-transform duration-[250ms] ease-in-out md:aspect-[5/7] md:w-full md:max-w-[360px]"
            style={{
              backgroundColor: getCardBorderColor(initialCard.border_color),
              transform: isFlipping ? 'rotateY(90deg)' : 'rotateY(0deg)',
              opacity: isFlipping ? 0.5 : isImageLoaded ? 1 : 0,
            }}
          >
            <CardImage
              src={imageUrl}
              alt={displayData.name}
              loading="eager"
              fetchPriority="high"
              onLoad={() => setIsImageLoaded(true)}
              className="block max-h-[55vh] w-auto max-w-full object-contain md:h-full md:max-h-none md:w-full md:object-cover"
              style={getCardRadiusStyle(initialCard.set_code)}
            />
          </div>

          {/* Flip button — always reserves space, visible only for double-sided cards */}
          <button
            onClick={handleFlip}
            disabled={!hasMultipleFaces}
            className={cn(
              'font-display flex items-center gap-2 border-2 border-[#111111] px-4 py-2 text-[11px] font-bold tracking-[0.1em] text-[#111111] uppercase hover:bg-[#111111] hover:text-white',
              !hasMultipleFaces && 'invisible'
            )}
          >
            <ArrowsClockwiseIcon className="h-4 w-4" />
            Flip card
          </button>
        </div>

        {/* Details Section */}
        <div className="flex w-full flex-col bg-white p-6 text-[#111111] md:w-1/2 md:overflow-y-auto md:p-8">
          <div className="flex-1">
            {/* Header: name + badge */}
            <div className="mb-5">
              <h2 className="font-display mb-2 text-2xl font-[800] tracking-[-0.01em] text-[#111111] uppercase sm:text-3xl">
                {displayName}
              </h2>
              {initialCard.similarity !== undefined && (
                <span className="font-display border-2 border-[#111111] px-2 py-0.5 text-[11px] font-bold tracking-wide text-[#111111] uppercase">
                  {(initialCard.similarity * 100).toFixed(0)}% match
                </span>
              )}
            </div>

            {/* Type / mana — card metadata, tight to header */}
            <p
              className={cn(
                'font-mono text-[13px] leading-snug text-[#111111]',
                isFlipping ? 'opacity-0' : 'opacity-100'
              )}
            >
              <span>{displayData.type_line || '—'}</span>{' '}
              <span className="px-1.5 text-[#7A7670]" aria-hidden="true">
                •
              </span>
              <span>
                <SymbolText text={displayData.mana_cost || 'None'} />
              </span>
            </p>

            {/* Content sections — distinct blocks, generous spacing */}
            <div
              className={cn(
                'mt-6 space-y-6',
                isFlipping ? 'opacity-0' : 'opacity-100'
              )}
            >
              <div className="border-t border-[#E8E5DE] pt-6">
                <span className="font-display mb-3 block text-[10px] font-bold tracking-[0.16em] text-[#7A7670] uppercase">
                  Oracle Text
                </span>

                {isSharedFace && fullCard?.faces ? (
                  <div className="flex flex-col">
                    {fullCard.faces.map((face, idx) => (
                      <div
                        key={idx}
                        className={
                          idx > 0 ? 'mt-6 border-t border-[#E8E5DE] pt-6' : ''
                        }
                      >
                        <p className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[#111111]">
                          <SymbolText
                            text={face.oracle_text || 'No oracle text.'}
                          />
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[#111111]">
                    <SymbolText
                      text={displayData.oracle_text || 'No oracle text.'}
                    />
                  </p>
                )}
              </div>

              {(fullCard?.uniqueness ?? initialCard.uniqueness) != null && (
                <div className="border-t border-[#E8E5DE] pt-6">
                  <span className="font-display mb-3 block text-[10px] font-bold tracking-[0.16em] text-[#7A7670] uppercase">
                    Uniqueness
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 bg-[#F0EDE6]">
                      <div
                        className="h-full bg-[#111111]"
                        style={{
                          width: `${Math.max(2, fullCard?.uniqueness ?? initialCard.uniqueness ?? 0)}%`,
                        }}
                      />
                    </div>
                    <span className="font-mono text-[11px] font-bold text-[#111111]">
                      {(
                        fullCard?.uniqueness ??
                        initialCard.uniqueness ??
                        0
                      ).toFixed(0)}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Footer: External Links + Action Button */}
          <div className="mt-auto pt-6">
            {/* External Links */}
            <div className="flex flex-col pb-6">
              <span className="font-display mb-3 block text-[10px] font-bold tracking-[0.16em] text-[#7A7670] uppercase">
                External Links
              </span>
              <div className="flex flex-wrap gap-2">
                <a
                  href={scryfallUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-display flex items-center gap-2 border-2 border-[#111111] px-3 py-1.5 text-[11px] font-bold tracking-wide text-[#111111] uppercase hover:bg-[#111111] hover:text-white"
                >
                  Scryfall
                </a>
                <a
                  href={edhrecUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-display flex items-center gap-2 border-2 border-[#111111] px-3 py-1.5 text-[11px] font-bold tracking-wide text-[#111111] uppercase hover:bg-[#111111] hover:text-white"
                >
                  EDHREC
                </a>
                <a
                  href={moxfieldUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-display flex items-center gap-2 border-2 border-[#111111] px-3 py-1.5 text-[11px] font-bold tracking-wide text-[#111111] uppercase hover:bg-[#111111] hover:text-white"
                >
                  Moxfield
                </a>
              </div>
            </div>

            {/* Action Button - Separator moved here */}
            <div className="border-t border-[#E8E5DE] pt-6">
              <Link
                to={
                  initialCard.face_ix > 0
                    ? `/card/${initialCard.oracle_id}?face=${initialCard.face_ix}`
                    : `/card/${initialCard.oracle_id}`
                }
                onClick={onClose}
                className="font-display flex w-full items-center justify-center gap-2 border-2 border-[#111111] bg-[#111111] px-6 py-3 text-[13px] font-bold tracking-[0.08em] text-white uppercase hover:bg-[#333]"
              >
                <MagnifyingGlassIcon className="h-4 w-4" />
                Find Similar Cards
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
