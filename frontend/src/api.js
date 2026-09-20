/** FastAPI answers a validation failure with a list of field errors, which used to
 *  reach the screen as "[object Object]". */
function message(body, res) {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e) =>
        [e.loc?.filter((part) => part !== 'body').join('.'), e.msg || 'invalid']
          .filter(Boolean)
          .join(': '),
      )
      .join('; ')
  }
  return `${res.status} ${res.statusText}`
}

async function req(path, options) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 204) return null
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(message(body, res))
  return body
}

export const api = {
  // Reads take a signal so a load for a day you have left can be dropped rather than
  // left to arrive later and paint the wrong day.
  day: (day, signal) => req(`/api/day?day=${encodeURIComponent(day)}`, { signal }),
  week: (start, days = 7, signal) =>
    req(`/api/week?start=${encodeURIComponent(start)}&days=${days}`, { signal }),
  create: (block) => req('/api/blocks', { method: 'POST', body: JSON.stringify(block) }),
  patch: (id, changes) =>
    req(`/api/blocks/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  remove: (id) => req(`/api/blocks/${id}`, { method: 'DELETE' }),
}
