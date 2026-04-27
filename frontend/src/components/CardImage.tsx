import { memo, useState } from 'react'
import { CardImageFallback } from './errors/CardImageFallback'

type CardImageProps = {
  src: string
  alt: string
  oracleText?: string
  manaCost?: string
  className?: string
  onLoad?: () => void
}

function CardImageComponent({ src, alt, oracleText, manaCost, className, onLoad }: CardImageProps) {
  const [hasError, setHasError] = useState(false)
  const [isLoaded, setIsLoaded] = useState(false)

  if (!src || hasError) {
    return <CardImageFallback alt={alt} oracleText={oracleText} manaCost={manaCost} className={className} />
  }

  return (
    <img
      src={src}
      alt={alt}
      className={[
        className ?? '',
        'transition-opacity duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
        isLoaded ? 'opacity-100' : 'opacity-0',
      ].join(' ')}
      loading="lazy"
      decoding="async"
      onLoad={() => {
        setIsLoaded(true)
        onLoad?.()
      }}
      onError={() => setHasError(true)}
    />
  )
}

export const CardImage = memo(CardImageComponent)
