/**
 * The two decisions the "your data" panel makes before it offers you a button.
 *
 * Both are pure, so they can be tested without a browser, and both exist to say something
 * *before* the destructive step rather than after it: whether the file you picked is a sundial
 * export at all, and what is in it.
 *
 * This is not the authority. The server checks the file again, and its refusals are the ones
 * that count — this is the panel declining to offer a button that is going to fail, and telling
 * you what that button will do while you can still walk away.
 */

/** Must match `FORMAT` in backend/export.py. The format, not the filename, is what makes a
 *  file an export: the filename is the first thing a person changes. */
export const FORMAT = 'sundial-export'

/** The newest export format this build understands. Must match `VERSION` in export.py. */
export const VERSION = 1

/** The exact words the server requires before it will replace a database.
 *  Must match `IMPORT_CONFIRMATION` in backend/app.py. Deliberately not "true": a request that
 *  wipes everything should be impossible to send by accident, and readable when found in a log. */
export const CONFIRMATION = 'replace everything'

/** Every table a complete export carries — the same list as `TABLES` in backend/export.py.
 *  A file missing one of these is refused here as well as there, because "missing" and "empty"
 *  are the same thing once imported, so the partial file would delete the part it left out. */
export const TABLES = ['calendars', 'blocks', 'events', 'sync_log', 'push_sent']

/** The tables a person would recognise, and what to call them when counting them.
 *  The bookkeeping tables travel in the file and stay out of the sentence: naming them adds a
 *  word to read and nothing to know. */
const SPEAKABLE = [
  ['blocks', 'block'],
  ['events', 'event'],
  ['calendars', 'calendar'],
]

/**
 * What can be said about a parsed file without asking the server.
 *
 * Returns `{ok: true, counts, says}` or `{ok: false, why}` — never throws, because every one of
 * these outcomes ends up as a sentence on screen and an exception would only be caught to
 * produce one.
 */
export function summarize(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { ok: false, why: 'that is not a sundial export.' }
  }
  if (payload.format !== FORMAT) {
    return { ok: false, why: 'that is not a sundial export.' }
  }
  if (!Number.isInteger(payload.version) || payload.version > VERSION) {
    return { ok: false, why: 'that file was written by a newer sundial. Upgrade first.' }
  }
  const tables = payload.tables
  if (!tables || typeof tables !== 'object') {
    return { ok: false, why: 'that export has no tables in it.' }
  }
  const missing = TABLES.filter((name) => !Array.isArray(tables[name]))
  if (missing.length) {
    return { ok: false, why: `that export is incomplete — no ${missing.join(', ')}.` }
  }
  const counts = Object.fromEntries(TABLES.map((name) => [name, tables[name].length]))
  return { ok: true, counts, says: describe(counts) }
}

/** "12 blocks, 3 events and 1 calendar" — or "nothing at all", which is worth saying out loud
 *  rather than rendering as an empty list of zeroes. */
export function describe(counts) {
  const parts = SPEAKABLE.filter(([name]) => counts[name] > 0).map(([name, noun]) => {
    const n = counts[name]
    return `${n} ${noun}${n === 1 ? '' : 's'}`
  })
  if (!parts.length) return 'nothing at all'
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}
