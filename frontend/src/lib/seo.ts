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
/** Default social share image (use /og-default.png when you add a dedicated asset). */
export const DEFAULT_OG_IMAGE_PATH = '/vite.svg'
