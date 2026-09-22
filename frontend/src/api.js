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

import { CONFIRMATION } from './datafile'

/** The name the server gave the download, so the panel does not invent a second one that could
 *  drift from the one `curl` users get from the same route. */
function filenameFrom(header) {
  return /filename="([^"]+)"/.exec(header || '')?.[1] || 'sundial.json'
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
  // The calendar is context for the plan, not the plan: these are read alongside the day
  // and a failure in them must never take the day down with it.
  calendars: (signal) => req('/api/calendars', { signal }),
  events: (day, signal) => req(`/api/events?day=${encodeURIComponent(day)}`, { signal }),
  syncCalendars: (ifStaleSeconds = 0) =>
    req('/api/calendars/sync', {
      method: 'POST',
      body: JSON.stringify({ if_stale_seconds: ifStaleSeconds }),
    }),
  setCalendar: (ref, enabled) =>
    req('/api/calendars', { method: 'PATCH', body: JSON.stringify({ ref, enabled }) }),
  // The one write that carries a secret. It goes out once, is written 0600 on the server, and
  // does not come back: the reply is the provider's state, not what was sent.
  saveCredentials: (provider, fields) =>
    req('/api/calendars/credentials', {
      method: 'POST',
      body: JSON.stringify({ provider, fields }),
    }),
  // Notifications. The subscription itself is made by the browser against the key the
  // server hands out; these three carry only what the server cannot work out on its own.
  pushKey: (signal) => req('/api/push/key', { signal }),
  subscribePush: (subscription) =>
    req('/api/push/subscribe', { method: 'POST', body: JSON.stringify(subscription) }),
  unsubscribePush: (endpoint) =>
    req('/api/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint }) }),
  testPush: () => req('/api/push/test', { method: 'POST' }),
  create: (block) => req('/api/blocks', { method: 'POST', body: JSON.stringify(block) }),
  patch: (id, changes) =>
    req(`/api/blocks/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  remove: (id) => req(`/api/blocks/${id}`, { method: 'DELETE' }),
  // Routines. A routine is a rule and its occurrences are not rows, so the three occurrence
  // routes name the routine and the day rather than an id nobody has: there is nothing to
  // address until a day has been changed, and creating the row is the server's job.
  routines: (signal) => req('/api/routines', { signal }),
  createRoutine: (routine) =>
    req('/api/routines', { method: 'POST', body: JSON.stringify(routine) }),
  patchRoutine: (id, changes) =>
    req(`/api/routines/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  removeRoutine: (id) => req(`/api/routines/${id}`, { method: 'DELETE' }),
  skipOccurrence: (id, day) =>
    req(`/api/routines/${id}/occurrences/${day}/skip`, { method: 'POST' }),
  patchOccurrence: (id, day, changes) =>
    req(`/api/routines/${id}/occurrences/${day}`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),
  resetOccurrence: (id, day) =>
    req(`/api/routines/${id}/occurrences/${day}`, { method: 'DELETE' }),
  // Leaving. The export is the one read that arrives as a download, so it is fetched whole
  // rather than through `req`: the reply's own Content-Disposition names the file.
  exportAll: async () => {
    const res = await fetch('/api/export')
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(message(body, res))
    return { document: body, filename: filenameFrom(res.headers.get('content-disposition')) }
  },
  // Destructive, and the phrase is the whole guard: an accidental call has to be impossible,
  // and a call found in a log has to be readable. The server holds the same string.
  importAll: (document) =>
    req('/api/import', {
      method: 'POST',
      body: JSON.stringify({ confirm: CONFIRMATION, document }),
    }),
}
