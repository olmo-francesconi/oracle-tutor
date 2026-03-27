const QUERY_PARAM = 'q'

export function readSubmittedQueryFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  const query = params.get(QUERY_PARAM)?.trim() ?? ''
  return query || null
}

export function writeSubmittedQueryToUrl(query: string | null) {
  const url = new URL(window.location.href)
  const params = new URLSearchParams(url.search)

  if (query) {
    params.set(QUERY_PARAM, query)
  } else {
    params.delete(QUERY_PARAM)
  }

  const nextSearch = params.toString()
  const nextUrl = `${url.pathname}${nextSearch ? `?${nextSearch}` : ''}`
  window.history.pushState({ query }, '', nextUrl)
}
