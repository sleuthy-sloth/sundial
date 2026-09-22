/** Templates: the words for a day structure, and the few list edits that are not a write.
 *
 *  A pure module, like `rollover.js` and `art.js`, because everything in it is worth asserting
 *  without a browser: what a template says about itself in a list, whether it can be applied at
 *  all, and what happens to the lines when one is moved or taken out.
 *
 *  The server is still the authority on what a template *is* — `backend/services/templates.py`
 *  owns applying, the order items are stored in, and every refusal. What lives here is the local
 *  half: the sentence a row reads as, and the list edits made on screen before the whole list is
 *  sent back in one PUT.
 *
 *  An item's hour is `start_min` in minutes past midnight, or null. Null is not midnight and is
 *  never rendered as a time: it is Anytime, which is the one thing a template item is allowed to
 *  leave unsaid.
 */

import { durText, hhmm } from './time.js'

/** What a line starts as when you add one. No hour, because most of a template is usually
 *  Anytime first and a time later — and an item with no hour is a complete item, not a draft. */
export const NEW_ITEM = { title: 'New item', start_min: null, duration_min: 30, color: 'slate' }

/** Is this item at a time, or in Anytime? */
export const timed = (item) => item.start_min != null

/** Every hour on the item list, or '' when none of them has one. */
export function timeSpan(items = []) {
  const minutes = items.filter(timed).map((i) => i.start_min)
  if (!minutes.length) return ''
  return `${hhmm(Math.min(...minutes))}–${hhmm(Math.max(...minutes))}`
}

/** What is planned, as the app says lengths everywhere else: "2h 30m". */
export const plannedTime = (items = []) =>
  durText(items.reduce((total, i) => total + i.duration_min, 0))

/** The one line a template reads as in a list.
 *
 *  Says what is true and stops. "Nothing in it yet" is the honest empty state rather than a
 *  count of zero, and the span is left out when no item has an hour, because "Anytime" repeated
 *  four times is not a time range. */
export function describeTemplate(template) {
  const items = template?.items ?? []
  if (!items.length) return 'Nothing in it yet'
  const count = `${items.length} item${items.length === 1 ? '' : 's'}`
  const span = timeSpan(items)
  const anytime = items.filter((i) => !timed(i)).length
  const parts = [count, span || null, anytime ? `${anytime} anytime` : null].filter(Boolean)
  return `${parts.join(' · ')} · ${plannedTime(items)}`
}

/** Whether applying would do anything. A template with no lines has nothing to add, and the
 *  server refuses it with a sentence — so the button says so by being off. */
export const canApply = (template) => (template?.items?.length ?? 0) > 0

/** Move a line up or down. Out of range is the same list back rather than an error: the
 *  buttons that call this are disabled at the ends, and a stale index should not be a crash. */
export function reorder(items, from, to) {
  if (to < 0 || to >= items.length || from < 0 || from >= items.length || from === to) return items
  const next = [...items]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

/** Take a line out, by position — which is all the screen knows about a line, since the ids
 *  change every time the list is saved. */
export const withoutItem = (items, index) => items.filter((_, i) => i !== index)

/** Add a line at the end. */
export const withItem = (items, item = NEW_ITEM) => [...items, { ...item }]

/** The body for `PUT /api/templates/{id}/blocks`: the lines, and nothing else.
 *
 *  Ids and sort_order are the server's to assign — the position in this array is the order —
 *  and sending them back would be this module claiming to know something it was told. */
export const payloadItems = (items = []) =>
  items.map((i) => ({
    title: i.title,
    start_min: i.start_min ?? null,
    duration_min: i.duration_min,
    color: i.color,
    icon: i.icon ?? '',
    notes: i.notes ?? '',
  }))

/** What was just added, in one sentence. Not a count of what the day now holds: the answer to
 *  applying is what applying did. */
export function describeApply(result) {
  const n = result?.created?.length ?? 0
  if (!n) return 'Nothing was added.'
  return `${n} block${n === 1 ? '' : 's'} added from ${result.name}.`
}
