import { Helmet } from 'react-helmet-async'
import { getBaseUrl, DEFAULT_OG_IMAGE_PATH } from '../lib/seo'

export interface PageSEOProps {
  title: string
  description: string
  /** Path including search (e.g. "/", "/card/abc123", "/search?q=damage") */
  path: string
  /** Absolute URL for og:image (optional). If not set, uses default. */
  image?: string
}

export function PageSEO({ title, description, path, image }: PageSEOProps) {
  const baseUrl = getBaseUrl()
  const canonical = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  const imageUrl = image ?? `${baseUrl}${DEFAULT_OG_IMAGE_PATH}`

  return (
    <Helmet>
      <title>{title}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={canonical} />
      <meta property="og:type" content="website" />
      <meta property="og:url" content={canonical} />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:image" content={imageUrl} />
      <meta property="og:site_name" content="Oracle Tutor" />
      <meta property="og:locale" content="en" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={imageUrl} />
    </Helmet>
  )
}
