import { memo, useState } from 'react'

type CardImageProps = {
  src: string
  alt: string
  className?: string
}

function CardImageComponent({ src, alt, className }: CardImageProps) {
  const [hasError, setHasError] = useState(false)

  if (!src || hasError) {
    return (
      <div
        className={className}
        role="img"
        aria-label={alt ? `Placeholder for ${alt}` : 'Card image unavailable'}
      />
    )
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
