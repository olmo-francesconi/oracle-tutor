import { SymbolText } from '../SymbolText'

type CardImageFallbackProps = {
  alt: string
  oracleText?: string
  manaCost?: string
  className?: string
}

export function CardImageFallback({ alt, oracleText, manaCost, className }: CardImageFallbackProps) {
  return (
    <div className={['grid h-full grid-rows-[auto_1fr] overflow-hidden bg-[#b7b7b2]', className ?? ''].join(' ')} aria-hidden="true">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-b-2 border-ot-ink bg-ot-bg p-2">
        <p className="m-0 min-w-0 truncate font-display text-[0.95rem] font-black uppercase leading-[0.94] tracking-[-0.02em] text-ot-ink">
          {alt || 'Card name unavailable'}
        </p>
        {manaCost ? (
          <p className="m-0 justify-self-end text-[0.82rem] leading-none text-ot-ink" aria-hidden="true">
            <SymbolText text={manaCost} />
          </p>
        ) : null}
      </div>
      <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] p-2">
        <div className="min-h-0 overflow-hidden">
          <p className="m-0 max-w-[18ch] text-[0.65rem] leading-[1.45] text-ot-ink">
            {oracleText || 'Oracle text unavailable.'}
          </p>
        </div>
        <p className="m-0 text-[0.625rem] uppercase tracking-[0.12em] text-ot-red">
          Error loading the image
        </p>
      </div>
    </div>
  )
}
