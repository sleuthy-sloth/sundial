/** Repeats: the words for a rule, and how a routine occurrence differs from a block.
 *
 *  The rule itself lives on the server — `services/routines.py` decides which days a routine
 *  lands on, and it is the only place that decision is made. What is here is the local half:
 *  the labels a person reads, the set of days a click adds or removes, and the two facts the
 *  editor needs to send a write to the right place.
 *
 *  Days are ISO numbers, 1 is Monday and 7 is Sunday, the same numbering the API and the
 *  database use. Nothing here converts between numberings, because a conversion is where a
 *  Saturday becomes a Friday.
 */

/** The seven buttons, in the order a week is read in. */
export const WEEKDAY_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]

/** The repeat control's options, in the plan's order. `value` is what the API stores. */
export const REPEATS = [
  { value: 'daily', label: 'Every day' },
  { value: 'weekdays', label: 'Weekdays' },
  { value: 'weekends', label: 'Weekends' },
  { value: 'weekly_interval', label: 'Every week' },
  { value: 'selected_weekdays', label: 'Custom weekdays' },
]

/** "Every week" or "Every 2 weeks" — the one option whose wording depends on a number. */
export const everyWeeks = (n = 1) => (Number(n) > 1 ? `Every ${Number(n)} weeks` : 'Every week')

/** Which day of the week a 'YYYY-MM-DD' is, as 1 (Monday) to 7 (Sunday).
 *
 *  Parsed at noon rather than midnight so a day is never read as the day before: a timezone
 *  ahead of UTC would otherwise turn midnight into the previous evening in some locales. */
export const isoWeekday = (iso) => {
  const at = new Date(`${iso}T12:00:00`)
  return at.getDay() === 0 ? 7 : at.getDay()
}

/** The days to start from when a repeat is chosen.
 *
 *  Only two of the rules carry a set of days: "custom weekdays" is nothing but the set, and
 *  "every week" is a single weekday — the one the block is already on, which is why this is
 *  asked for a day. The other three say what they mean on their own, and pre-selecting days
 *  they ignore would be showing a choice that is not being made. */
export const weekdaysFor = (kind, day) => (kind === 'weekly_interval' ? [isoWeekday(day)] : [])

/** Add a day, or take it away. Sorted and deduplicated, which is the order the API stores. */
export const toggleWeekday = (days = [], n) =>
  days.includes(n) ? days.filter((d) => d !== n) : [...days, n].sort((a, b) => a - b)

/** Is this block an occurrence of a routine rather than a block of its own?
 *
 *  Asked of the `source` the API puts on every row, not of the shape of the row: an occurrence
 *  is a block in every visible way, and working it out by guessing is how the two drift apart. */
export const isOccurrence = (block) => block?.source === 'routine'

/** The routine a block is an occurrence of, and the day it is, or nulls. */
export const occurrenceOf = (block) =>
  isOccurrence(block)
    ? { routine_id: block.routine_id, day: block.occurrence_day ?? block.day }
    : { routine_id: null, day: null }

/** Has this day been told something different from what the routine says?
 *
 *  Compared field by field against the routine, which is the definition of an override: a day
 *  that matches its rule has nothing written down, and offering to undo that would be offering
 *  to undo nothing. */
export const differsFromRoutine = (block, routine) => {
  if (!block || !routine) return false
  return ['title', 'start_min', 'duration_min', 'color', 'icon', 'notes'].some(
    (field) => block[field] !== routine[field],
  )
}
