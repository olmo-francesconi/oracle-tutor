type HeadConfig = {
  title: string
  description: string
  canonical: string
  ogImage?: string | null
  ogType?: 'website' | 'article'
  robots?: 'index,follow' | 'noindex,follow' | 'noindex,nofollow'
}

function upsertNamedMeta(name: string, content: string): void {
  let tag = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('name', name)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

function upsertPropertyMeta(property: string, content: string): void {
  let tag = document.querySelector<HTMLMetaElement>(`meta[property="${property}"]`)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('property', property)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

function upsertLink(rel: string, href: string): void {
  let tag = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (!tag) {
    tag = document.createElement('link')
    tag.setAttribute('rel', rel)
    document.head.appendChild(tag)
  }
  tag.setAttribute('href', href)
}

function removePropertyMeta(property: string): void {
  document.querySelector(`meta[property="${property}"]`)?.remove()
}

function removeNamedMeta(name: string): void {
  document.querySelector(`meta[name="${name}"]`)?.remove()
}

export function applyDocumentHead(cfg: HeadConfig): void {
  document.title = cfg.title
  upsertNamedMeta('description', cfg.description)
  upsertNamedMeta('robots', cfg.robots ?? 'index,follow')
  upsertLink('canonical', cfg.canonical)

  upsertPropertyMeta('og:title', cfg.title)
  upsertPropertyMeta('og:description', cfg.description)
  upsertPropertyMeta('og:url', cfg.canonical)
  upsertPropertyMeta('og:type', cfg.ogType ?? 'website')
  upsertPropertyMeta('og:site_name', 'Oracle Tutor')

  upsertNamedMeta('twitter:card', cfg.ogImage ? 'summary_large_image' : 'summary')
  upsertNamedMeta('twitter:title', cfg.title)
  upsertNamedMeta('twitter:description', cfg.description)

  if (cfg.ogImage) {
    upsertPropertyMeta('og:image', cfg.ogImage)
    upsertNamedMeta('twitter:image', cfg.ogImage)
  } else {
    removePropertyMeta('og:image')
    removeNamedMeta('twitter:image')
  }
}

const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined)?.replace(/\/+$/, '') ?? ''

export function getAppOrigin(): string {
  if (APP_URL) return APP_URL
  if (typeof window !== 'undefined') return window.location.origin
  return ''
}
