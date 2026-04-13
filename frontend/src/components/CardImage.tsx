import { memo, useState } from 'react'
import { CardImageFallback } from './errors/CardImageFallback'

type CardImageProps = {
  src: string
  alt: string
  oracleText?: string
  manaCost?: string
  className?: string
}

function CardImageComponent({ src, alt, oracleText, manaCost, className }: CardImageProps) {
  const [hasError, setHasError] = useState(false)

  if (!src || hasError) {
    return <CardImageFallback alt={alt} oracleText={oracleText} manaCost={manaCost} className={className} />
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading="lazy"
      decoding="async"
      onError={() => setHasError(true)}
    />
  )
}

export const CardImage = memo(CardImageComponent)
