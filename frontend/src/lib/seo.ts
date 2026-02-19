/**
 * Base URL for canonical and Open Graph URLs.
 * Prefer VITE_APP_URL in production so crawlers get stable URLs.
 */
export function getBaseUrl(): string {
  if (import.meta.env.VITE_APP_URL) {
    return import.meta.env.VITE_APP_URL.replace(/\/$/, '')
  }
  if (typeof window !== 'undefined') {
    return window.location.origin
  }
  return 'https://oracletutor.org'
}

export const DEFAULT_TITLE = 'Oracle Tutor'
export const DEFAULT_DESCRIPTION =
  'Find Magic: The Gathering cards by semantic meaning. Search by what cards do, not just keywords.'
/** Default social share image. Prefer a 1200×630 asset at /og-default.png for better previews. */
export const DEFAULT_OG_IMAGE_PATH = '/favicon.svg'
