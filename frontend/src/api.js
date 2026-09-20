async function req(path, options) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 204) return null
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`)
  return body
}

export const api = {
  day: (day) => req(`/api/day?day=${encodeURIComponent(day)}`),
  create: (block) => req('/api/blocks', { method: 'POST', body: JSON.stringify(block) }),
  patch: (id, changes) =>
    req(`/api/blocks/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  remove: (id) => req(`/api/blocks/${id}`, { method: 'DELETE' }),
}
