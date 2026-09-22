/** The week, read as capacity rather than as a calendar grid.
 *
 *  A grid answers "when is this"; this answers "how much of it is left". Everything a day
 *  column says is worked out here, from the figures the server already counted, so the screen
 *  holds no arithmetic of its own and every number on it can be tested without a browser.
 *
 *  The week starts on Monday. That is a choice, not a locale default: the plan's own sketch
 *  runs MON to SUN, and a planner whose first column moved with `Intl` would be a different
 *  instrument in a different country.
 */

import { DAY_MIN, durText, shiftDay } from './time.js'

/** How many days a week has. Everything here is fixed at seven: the month has its own view. */
const WEEK = 7

/** The Monday of the week a day is in. */
export function weekStart(iso) {
  // getDay() is 0 on Sunday, and Sunday is the last day of the week that began six days
  // earlier — not the first day of a new one.
  const dow = new Date(`${iso}T12:00:00`).getDay()
  return shiftDay(iso, -((dow + 6) % 7))
}

/** The seven days of the week a day is in, Monday first. */
export function weekDays(iso) {
  const monday = weekStart(iso)
  return Array.from({ length: WEEK }, (_, i) => shiftDay(monday, i))
}

/** The week as a heading reads it: "21 – 27 Sep", the month named at both ends when the week
 *  straddles one, and the year at the far end when it straddles that too. A week that says
 *  only "28 – 3" is a week whose dates cannot be checked. */
export function weekTitle(iso) {
  const days = weekDays(iso)
  const first = new Date(`${days[0]}T12:00:00`)
  const last = new Date(`${days[WEEK - 1]}T12:00:00`)
  const month = (d) => d.toLocaleDateString(undefined, { month: 'short' })
  const sameMonth = first.getMonth() === last.getMonth() && first.getFullYear() === last.getFullYear()
  const sameYear = first.getFullYear() === last.getFullYear()
  const from = `${first.getDate()} ${month(first)}`
  const to = sameMonth ? `${last.getDate()}` : `${last.getDate()} ${month(last)}`
  const withYear = sameYear ? `${from} – ${to}` : `${from} ${first.getFullYear()} – ${to} ${last.getFullYear()}`
  return withYear
}

/** The weekday as a column heading reads it: three letters, from the locale.
 *
 *  Not the narrow form the old strip used: "T" is Tuesday and Thursday, and "S" is half the
 *  weekend. A week you have to decode is not a week you can glance at. */
export function shortDow(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' })
}

/** A figure as a column reads it: "4h20" fits in a seventh of a phone, "4h 20m" does not.
 *  Nothing planned is a dash rather than a zero — an empty day is not a day of no time. */
export function compact(minutes) {
  const total = Math.max(0, Math.round(minutes || 0))
  if (!total) return '—'
  if (total < 60) return `${total}m`
  const spare = total % 60
  const hours = Math.floor(total / 60)
  return spare ? `${hours}h${String(spare).padStart(2, '0')}` : `${hours}h`
}

/** Where a day's time went, in minutes, as three widths that add up to the busy time exactly.
 *
 *  Your plan and the calendar can share an hour, so the three parts are the plan alone, the
 *  hour both of them claim, and the calendar alone. Stacking the two totals side by side
 *  instead would draw the shared hour twice and a bar would be wider than the day.
 */
export function barOf(day) {
  const planned = Math.max(0, day?.planned_minutes ?? 0)
  const calendar = Math.max(0, day?.calendar_busy_minutes ?? 0)
  const busy = Math.max(0, DAY_MIN - (day?.open_minutes ?? DAY_MIN))
  const both = Math.max(0, Math.min(planned + calendar - busy, Math.min(planned, calendar)))
  const share = (minutes) => `${(minutes / DAY_MIN) * 100}%`
  return {
    busy,
    plan: share(planned - both),
    both: share(both),
    calendar: share(calendar - both),
    planned,
    calendar_minutes: calendar,
  }
}

/** The sentence a day column is read as, rather than a list of numbers announced one at a time.
 *  Quiet by design: what is planned and what is open, and nothing about being behind. */
export function daySentence(entry, today) {
  const date = new Date(`${entry.day}T12:00:00`)
  const named = date.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  const said = []
  said.push(entry.planned_minutes ? `${durText(entry.planned_minutes)} planned` : 'nothing planned')
  if (entry.calendar_busy_minutes) said.push(`${durText(entry.calendar_busy_minutes)} on the calendar`)
  said.push(`${durText(entry.open_minutes)} open`)
  if (entry.block_count) said.push(entry.block_count === 1 ? '1 block' : `${entry.block_count} blocks`)
  if (entry.completed_count) said.push(`${entry.completed_count} done`)
  if (entry.day === today) said.push('today')
  return `${named}: ${said.join(', ')}`
}

/** What a day with nothing in it is: a full day, open. A day the week could not read is not
 *  silently drawn as a busy one, and it is not drawn as absent either. */
export function emptyDay(day) {
  return {
    day,
    planned_minutes: 0,
    open_minutes: DAY_MIN,
    block_count: 0,
    completed_count: 0,
    calendar_busy_minutes: 0,
  }
}
