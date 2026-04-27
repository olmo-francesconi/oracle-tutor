import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getCardImageUrl } from '../lib/cards'
import type { Card } from '../types/api'
import { useCardQuery } from '../public/useCardQuery'
import { CardImage } from './CardImage'
import { SymbolText } from './SymbolText'

type Props = {
  oracleId: string | null
  similarity?: number | null
  onClose: () => void
  onFindSimilar?: (oracleId: string, name: string, faceIx: number) => void
}

const ANIMATION_MS = 240

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"]), input, textarea, select'

const TWO_SIDED_LAYOUTS = new Set([
  'transform',
  'modal_dfc',
  'double_faced_token',
  'reversible_card',
  'meld',
  'art_series',
])

function hasSeparateBackFace(card: Card): boolean {
  const faces = card.faces ?? []
  if (faces.length < 2) return false
  return Boolean(card.layout && TWO_SIDED_LAYOUTS.has(card.layout))
}

function formatPercentage(value: number): string {
  return `${Math.round(value * 100)}%`
}

type FaceLike = {
  name?: string | null
  mana_cost?: string | null
  type_line?: string | null
  oracle_text?: string | null
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ot-line py-2.5 last:border-b-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="m-0 text-right font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.01em] text-ot-ink">
        {value}
      </dd>
    </div>
  )
}

function FaceBlock({
  name,
  manaCost,
  typeLine,
  oracleText,
  onFindSimilar,
}: {
  name: string
  manaCost?: string | null
  typeLine?: string | null
  oracleText?: string | null
  onFindSimilar?: () => void
}) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-4">
        <h3 className="m-0 font-display text-[1.55rem] font-black uppercase leading-[0.95] tracking-[-0.02em] text-ot-ink">
          {name}
        </h3>
        {manaCost ? (
          <p
            className="m-0 shrink-0 self-baseline whitespace-nowrap text-[0.95rem] leading-none text-ot-ink"
            aria-label={`Mana cost ${manaCost}`}
          >
            <SymbolText text={manaCost} />
          </p>
        ) : null}
      </div>
      {typeLine ? (
        <p className="m-0 text-[0.72rem] uppercase tracking-[0.18em] text-ot-muted">{typeLine}</p>
      ) : null}
      {oracleText ? (
        <div className="whitespace-pre-line text-[0.95rem] leading-[1.65] text-ot-ink">
          <SymbolText text={oracleText} />
        </div>
      ) : null}
      {onFindSimilar ? (
        <button
          type="button"
          onClick={onFindSimilar}
          className="mt-1 inline-flex w-fit cursor-pointer items-center gap-2 border-2 border-ot-ink bg-transparent px-3 py-2 font-display text-[0.7rem] font-black uppercase tracking-[0.14em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
        >
          <span>Find similar to {name}</span>
          <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor" aria-hidden="true">
            <path d="M3 8h9.5L9 4.5l1-1L15 8.5 10 13.5l-1-1L12.5 9H3z" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}

function CardDetailContent({
  card,
  similarity,
  faceIx,
  onFlip,
  onFindSimilar,
  onClose,
  closeButtonRef,
  titleId,
}: {
  card: Card
  similarity?: number | null
  faceIx: number
  onFlip: () => void
  onFindSimilar?: Props['onFindSimilar']
  onClose: () => void
  closeButtonRef: React.RefObject<HTMLButtonElement | null>
  titleId: string
}) {
  const faces = card.faces ?? []
  const isFlippable = hasSeparateBackFace(card)
  const isMultiFaceFlat = !isFlippable && faces.length > 1
  const activeFace = isFlippable ? faces[faceIx] ?? faces[0] : faces[0]

  const manaCost = isFlippable
    ? activeFace?.mana_cost ?? null
    : card.mana_cost ?? activeFace?.mana_cost ?? null
  const typeLine = isFlippable
    ? activeFace?.type_line ?? null
    : card.type_line ?? activeFace?.type_line ?? null
  const oracleText = isFlippable
    ? activeFace?.oracle_text ?? null
    : card.oracle_text ?? activeFace?.oracle_text ?? null
  const power = isFlippable ? activeFace?.power ?? null : card.power ?? activeFace?.power ?? null
  const toughness = isFlippable
    ? activeFace?.toughness ?? null
    : card.toughness ?? activeFace?.toughness ?? null
  const colors = (
    isFlippable ? activeFace?.colors ?? [] : card.colors ?? activeFace?.colors ?? []
  ).filter(Boolean)
  const set = card.set_code ? card.set_code.toUpperCase() : null
  const rarity = card.rarity ? card.rarity.toUpperCase() : null
  const cmc = typeof card.cmc === 'number' ? `${card.cmc}` : null
  const edhrec =
    typeof card.edhrec_rank === 'number' ? `#${card.edhrec_rank.toLocaleString()}` : null

  const displayName = isFlippable && activeFace?.name ? activeFace.name : card.name
  const imageSide: 'front' | 'back' = isFlippable && faceIx === 1 ? 'back' : 'front'
  const stackedFaces: FaceLike[] = isMultiFaceFlat ? faces : []

  return (
    <>
      <header className="grid grid-cols-[1fr_auto] items-stretch border-b-2 border-ot-ink bg-ot-bg min-h-[58px] max-[860px]:sticky max-[860px]:top-0 max-[860px]:z-20">
        <div className="flex flex-col justify-center gap-0.5 px-5 py-2 max-[720px]:px-4">
          <p className="eyebrow">
            {similarity != null ? `Match ${formatPercentage(similarity)}` : 'Card detail'}
          </p>
          <p className="m-0 font-display text-[0.78rem] font-black uppercase tracking-[0.02em] text-ot-ink">
            {[set, rarity].filter(Boolean).join(' · ') || 'Oracle catalogue'}
          </p>
        </div>
        <button
          type="button"
          ref={closeButtonRef}
          onClick={onClose}
          aria-label="Close card detail"
          className="flex w-[58px] cursor-pointer items-center justify-center border-0 border-l-2 border-ot-ink bg-transparent font-display text-[22px] font-black leading-none text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-red hover:text-white motion-reduce:transition-none"
        >
          <svg
            viewBox="0 0 16 16"
            className="h-3.5 w-3.5"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            aria-hidden="true"
          >
            <path d="M3 3l10 10M13 3L3 13" />
          </svg>
        </button>
      </header>

      <div className="grid min-h-0 grid-cols-[minmax(0,42%)_minmax(0,1fr)] overflow-hidden max-[860px]:grid-cols-1 max-[860px]:overflow-visible">
        <div className="relative flex items-center justify-center border-r-2 border-ot-ink bg-ot-line/40 p-7 max-[860px]:border-r-0 max-[860px]:border-b-2 max-[860px]:p-5">
          <div className="w-full max-w-[440px]">
            <CardImage
              key={`${card.oracle_id}-${faceIx}`}
              src={getCardImageUrl({ ...card, image_side: imageSide }, 'large')}
              alt={displayName}
              oracleText={oracleText ?? undefined}
              manaCost={manaCost ?? undefined}
              className="block aspect-[63/88] w-full rounded-xl object-cover shadow-[0_22px_40px_-26px_rgba(17,17,17,0.45)]"
            />
          </div>
          {isFlippable ? (
            <button
              type="button"
              onClick={onFlip}
              aria-label={`Show face ${((faceIx + 1) % faces.length) + 1} of ${faces.length}`}
              className="absolute bottom-4 right-4 flex cursor-pointer items-center gap-2 border-2 border-ot-ink bg-ot-bg px-3 py-2 font-display text-[0.7rem] font-black uppercase tracking-[0.14em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
            >
              <svg
                viewBox="0 0 16 16"
                className="h-3.5 w-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <path d="M2 6a5 5 0 0 1 9-3l2 2" strokeLinecap="round" />
                <path d="M13 4v3h-3" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M14 10a5 5 0 0 1-9 3l-2-2" strokeLinecap="round" />
                <path d="M3 12V9h3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Flip</span>
              <span className="text-ot-muted">
                {faceIx + 1}/{faces.length}
              </span>
            </button>
          ) : null}
        </div>

        <div className="flex min-h-0 flex-col overflow-y-auto max-[860px]:min-h-0 max-[860px]:overflow-visible">
          <div className="grid gap-5 px-7 py-7 max-[860px]:px-5 max-[860px]:py-6">
            {isMultiFaceFlat ? (
              <h2 id={titleId} className="sr-only">
                {displayName}
              </h2>
            ) : (
              <>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-5">
                  <h2
                    id={titleId}
                    className="m-0 font-display text-[clamp(2rem,3.4vw,3rem)] font-black uppercase leading-[0.9] tracking-[-0.025em] text-ot-ink"
                  >
                    {displayName}
                  </h2>
                  {manaCost ? (
                    <p
                      className="m-0 shrink-0 self-start whitespace-nowrap pt-1 text-[1.05rem] leading-none text-ot-ink"
                      aria-label={`Mana cost ${manaCost}`}
                    >
                      <SymbolText text={manaCost} />
                    </p>
                  ) : null}
                </div>

                <div className="h-0.5 w-full bg-ot-ink" aria-hidden="true" />
              </>
            )}

            {isMultiFaceFlat ? (
              <div className="grid gap-5">
                {stackedFaces.map((stackFace, index) => {
                  const faceName = stackFace.name ?? `Face ${index + 1}`
                  return (
                    <div key={`${faceName}-${index}`} className="grid gap-5">
                      {index > 0 ? (
                        <div className="h-px w-full bg-ot-line" aria-hidden="true" />
                      ) : null}
                      <FaceBlock
                        name={faceName}
                        manaCost={stackFace.mana_cost ?? null}
                        typeLine={stackFace.type_line ?? null}
                        oracleText={stackFace.oracle_text ?? null}
                        onFindSimilar={
                          onFindSimilar
                            ? () => onFindSimilar(card.oracle_id, faceName, index)
                            : undefined
                        }
                      />
                    </div>
                  )
                })}
              </div>
            ) : (
              <>
                {typeLine ? (
                  <p className="m-0 text-[0.78rem] uppercase tracking-[0.18em] text-ot-ink">
                    {typeLine}
                  </p>
                ) : null}

                {oracleText ? (
                  <div className="whitespace-pre-line text-[0.95rem] leading-[1.65] text-ot-ink">
                    <SymbolText text={oracleText} />
                  </div>
                ) : (
                  <p className="m-0 text-[0.85rem] italic text-ot-muted">
                    No oracle text on file.
                  </p>
                )}
              </>
            )}

            {isFlippable ? (
              <p className="m-0 text-[0.7rem] uppercase tracking-[0.16em] text-ot-muted">
                Face {faceIx + 1} of {faces.length}
              </p>
            ) : null}
          </div>

          <dl className="mt-auto grid gap-0 border-t-2 border-ot-ink bg-ot-bg px-7 py-4 max-[860px]:px-5">
            {power != null && toughness != null ? (
              <MetaRow label="Power · Toughness" value={`${power} / ${toughness}`} />
            ) : null}
            {cmc != null ? <MetaRow label="Mana value" value={cmc} /> : null}
            {colors.length > 0 ? <MetaRow label="Colors" value={colors.join(' · ')} /> : null}
            {edhrec ? <MetaRow label="EDHREC rank" value={edhrec} /> : null}
          </dl>

          {onFindSimilar && !isMultiFaceFlat ? (
            <div className="border-t-2 border-ot-ink">
              <button
                type="button"
                onClick={() =>
                  onFindSimilar(card.oracle_id, card.name, isFlippable ? faceIx : 0)
                }
                className="flex w-full cursor-pointer items-center justify-between border-0 bg-transparent px-7 py-4 text-left font-display text-[0.95rem] font-black uppercase tracking-[0.04em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none max-[860px]:px-5"
              >
                <span>Find similar cards</span>
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
                  <path d="M3 8h9.5L9 4.5l1-1L15 8.5 10 13.5l-1-1L12.5 9H3z" />
                </svg>
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </>
  )
}

export function CardDetailOverlay({ oracleId, similarity, onClose, onFindSimilar }: Props) {
  const [renderedOracleId, setRenderedOracleId] = useState<string | null>(oracleId)
  const [renderedSimilarity, setRenderedSimilarity] = useState<number | null | undefined>(
    similarity
  )
  const [isVisible, setIsVisible] = useState(false)
  const [faceIx, setFaceIx] = useState(0)
  const titleId = useId()

  const panelRef = useRef<HTMLDivElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const cardQuery = useCardQuery(renderedOracleId)
  const card = cardQuery.data

  useEffect(() => {
    if (oracleId) {
      let secondFrame = 0
      const firstFrame = requestAnimationFrame(() => {
        setRenderedOracleId((prev) => {
          if (prev !== oracleId) setFaceIx(0)
          return oracleId
        })
        setRenderedSimilarity(similarity)
        secondFrame = requestAnimationFrame(() => setIsVisible(true))
      })
      return () => {
        cancelAnimationFrame(firstFrame)
        if (secondFrame) cancelAnimationFrame(secondFrame)
      }
    }

    const hideFrame = requestAnimationFrame(() => setIsVisible(false))
    const clearTimer = window.setTimeout(() => {
      setRenderedOracleId(null)
      setRenderedSimilarity(null)
    }, ANIMATION_MS)
    return () => {
      cancelAnimationFrame(hideFrame)
      window.clearTimeout(clearTimer)
    }
  }, [oracleId, similarity])

  useEffect(() => {
    if (!renderedOracleId) return undefined

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const main = document.querySelector('main')
    if (main) main.setAttribute('inert', '')

    const focusFrame = requestAnimationFrame(() => {
      closeButtonRef.current?.focus()
    })

    return () => {
      cancelAnimationFrame(focusFrame)
      document.body.style.overflow = previousOverflow
      if (main) main.removeAttribute('inert')
      previousFocusRef.current?.focus()
    }
  }, [renderedOracleId])

  useEffect(() => {
    if (!isVisible) return undefined

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return

      const focusables = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      ).filter((el) => !el.hasAttribute('disabled') && el.offsetParent !== null)

      if (focusables.length === 0) {
        event.preventDefault()
        return
      }

      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement as HTMLElement | null

      if (event.shiftKey && (active === first || !panelRef.current.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isVisible, onClose])

  const handleBackdropClick = useMemo(
    () => (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) onClose()
    },
    [onClose]
  )

  const handleFlip = useMemo(
    () => () => {
      if (!card || !hasSeparateBackFace(card)) return
      const faceCount = card.faces?.length ?? 1
      setFaceIx((prev) => (prev + 1) % faceCount)
    },
    [card]
  )

  if (!renderedOracleId) return null

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={card ? titleId : undefined}
      aria-busy={cardQuery.isLoading}
      className="fixed inset-0 z-50 grid place-items-center max-[860px]:block max-[860px]:overflow-y-auto"
    >
      <div
        onClick={handleBackdropClick}
        className={[
          'fixed inset-0 bg-ot-ink/65 transition-opacity duration-[240ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none',
          isVisible ? 'opacity-100' : 'opacity-0',
        ].join(' ')}
        aria-hidden="true"
      />

      <div
        className="relative grid w-full place-items-center px-6 py-6 max-[860px]:block max-[860px]:p-0"
        onClick={handleBackdropClick}
      >
        <div
          ref={panelRef}
          className={[
            'relative grid max-h-[min(880px,90vh)] w-full max-w-[1080px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-2 border-ot-ink bg-ot-bg shadow-[0_36px_80px_-30px_rgba(17,17,17,0.55)]',
            'transition-[opacity,transform] duration-[240ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none',
            isVisible ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
            'max-[860px]:max-h-none max-[860px]:min-h-screen max-[860px]:overflow-visible max-[860px]:border-0',
          ].join(' ')}
        >
          {card ? (
            <CardDetailContent
              card={card}
              similarity={renderedSimilarity}
              faceIx={faceIx}
              onFlip={handleFlip}
              onFindSimilar={onFindSimilar}
              onClose={onClose}
              closeButtonRef={closeButtonRef}
              titleId={titleId}
            />
          ) : (
            <div className="grid grid-rows-[auto_minmax(0,1fr)]">
              <header className="grid grid-cols-[1fr_auto] items-stretch border-b-2 border-ot-ink min-h-[58px]">
                <div className="flex flex-col justify-center gap-0.5 px-5 py-2">
                  <p className="eyebrow">Card detail</p>
                  <p className="m-0 font-display text-[0.78rem] font-black uppercase tracking-[0.02em] text-ot-ink">
                    Loading
                  </p>
                </div>
                <button
                  type="button"
                  ref={closeButtonRef}
                  onClick={onClose}
                  aria-label="Close card detail"
                  className="flex w-[58px] cursor-pointer items-center justify-center border-0 border-l-2 border-ot-ink bg-transparent font-display text-[22px] font-black leading-none text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-red hover:text-white motion-reduce:transition-none"
                >
                  <svg
                    viewBox="0 0 16 16"
                    className="h-3.5 w-3.5"
                    stroke="currentColor"
                    strokeWidth="2"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path d="M3 3l10 10M13 3L3 13" />
                  </svg>
                </button>
              </header>
              <div className="grid grid-cols-[minmax(0,42%)_minmax(0,1fr)] max-[860px]:grid-cols-1">
                <div className="border-r-2 border-ot-ink bg-ot-line/40 p-7 max-[860px]:border-r-0 max-[860px]:border-b-2">
                  <div className="aspect-[63/88] w-full max-w-[440px] animate-ot-loading-pulse rounded-xl bg-[color:color-mix(in_srgb,var(--color-ot-line)_72%,var(--color-ot-bg))]" />
                </div>
                <div className="grid gap-4 p-7 max-[860px]:p-5">
                  <span className="block h-9 w-3/4 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                  <span className="block h-3 w-2/5 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                  <span className="block h-24 w-full animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_72%,var(--color-ot-bg))]" />
                </div>
              </div>
            </div>
          )}

          {cardQuery.isError && !cardQuery.data ? (
            <div className="absolute inset-0 grid place-items-center bg-ot-bg/95 p-6 text-center">
              <div className="grid gap-2">
                <p className="eyebrow text-ot-red">Detail unavailable</p>
                <p className="m-0 text-[0.85rem] text-ot-ink">
                  We could not load this card right now.
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  className="mt-3 cursor-pointer border-2 border-ot-ink bg-transparent px-4 py-2 font-display text-[0.78rem] font-black uppercase tracking-[0.12em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
                >
                  Dismiss
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>,
    document.body
  )
}
