const QUERY_PARAM = 'q'

export function readSubmittedQueryFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  const query = params.get(QUERY_PARAM)?.trim() ?? ''
  return query || null
}

export function writeSubmittedQueryToUrl(query: string | null) {
  const url = new URL(window.location.href)

  if (query) {
    url.searchParams.set(QUERY_PARAM, query)
  } else {
    url.searchParams.delete(QUERY_PARAM)
  }

  const nextUrl = `${url.pathname}${url.search}`
  window.history.pushState({ query }, '', nextUrl)
}
