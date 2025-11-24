import { useState, useEffect } from 'react';
import { ImageOff } from 'lucide-react';

interface CardImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  // No special props needed beyond standard img props for now
}

export function CardImage({ src, alt, className, ...props }: CardImageProps) {
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
  }, [src]);

  if (error) {
    return (
      <div 
        className={`flex flex-col items-center justify-center bg-[#1c1c1c] border border-white/10 text-white/20 select-none ${className}`}
        role="img" 
        aria-label={alt ? `Placeholder for ${alt}` : 'Image placeholder'}
      >
        <ImageOff size={32} className="mb-2 opacity-50" />
        <span className="text-xs font-medium text-center px-4">
          {alt || 'Image unavailable'}
        </span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setError(true)}
      {...props}
    />
  );
}
