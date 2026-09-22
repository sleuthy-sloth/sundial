/**
 * Yesterday's unfinished work: the three things that may happen to it, and what "leave there" is.
 *
 * A pure module, like `art.js` and `glance.js`, because the decisions in it are worth asserting
 * without a browser: whether the section is drawn at all, whether anything moves by itself, and
 * which of the three the server's setting means. The words live here too, so the panel and the
 * section cannot describe the same setting two different ways.
 *
 * The setting itself is not here and not in `localStorage`: it is a row in the database, because
 * the export carries the database and a preference kept in one browser would be the single part of
 * a person's setup that a backup silently drops. See `backend/services/settings.py`.
 */

/** The three answers, in the order the panel offers them. `value` is what the API stores. */
export const ROLLOVER_OPTIONS = [
  { value: 'ask', label: 'Ask me the next day' },
  { value: 'anytime', label: 'Move to Anytime automatically' },
  { value: 'leave', label: 'Leave on the original day' },
]

/** What the app does while nobody has chosen, and what an unrecognised answer falls back to. */
export const ROLLOVER_DEFAULT = 'ask'

/**
 * What to do about what was left, given the setting.
 *
 *   'ask'      draw the section and wait for a tap
 *   'move'     move every one of them to Anytime, without a section
 *   'nothing'  leave them on the day they were, and say nothing about it
 *
 * An unrecognised setting answers 'ask' rather than 'move'. Both are wrong about a build that
 * knows a fourth option, but only one of them writes to a day you have already had.
 */
export function rolloverAction(setting, waiting = []) {
  if (waiting.length === 0) return 'nothing'
  if (setting === 'anytime') return 'move'
  if (setting === 'leave') return 'nothing'
  return 'ask'
}

/**
 * Where a "leave there" is remembered: this tab, this day, and nowhere else.
 *
 * Not in the database, because it is not a decision about your plan — it is "not now", and writing
 * it down would be new user data to export, back up and explain. Not in `localStorage` either: the
 * key carries the day, so the entry cannot outlive the day it was about, and a stale one would be
 * a thing left from yesterday that never comes back except on the one day it cannot matter.
 */
export const dismissedKey = (day) => `sundial-left-there:${day}`

/** The ids this tab has already left alone today. Anything unreadable counts as nothing. */
export function dismissed(day) {
  try {
    const held = JSON.parse(sessionStorage.getItem(dismissedKey(day)) || '[]')
    return Array.isArray(held) ? held : []
  } catch {
    return []
  }
}

/** Leave one alone for the rest of this tab's day, and answer with the list it makes. */
export function leaveThere(day, id) {
  const held = dismissed(day)
  const next = held.includes(id) ? held : [...held, id]
  try {
    sessionStorage.setItem(dismissedKey(day), JSON.stringify(next))
  } catch {
    // Nothing to keep it in. The row is still on yesterday, so the worst case is being asked
    // about it a second time — which is a smaller thing than a section that will not respond.
  }
  return next
}

/** What the section actually draws: everything left, less what this tab has left alone. */
export function stillWaiting(waiting = [], gone = []) {
  return waiting.filter((block) => !gone.includes(block.id))
}
