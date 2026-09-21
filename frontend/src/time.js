// The hour is the app's unit of truth: 72px makes half an hour 36px, which is the
// smallest slot that can hold a title and a time without clipping. --hour-h in styles.css
// must match this.
const HOUR_PX = 72
const SNAP_MIN = 15
const DAY_MIN = 1440

// Local date, not UTC: a plan for "today" must not shift by timezone.
const todayISO = () => new Date().toLocaleDateString('sv-SE')
const minsNow = () => {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}
const snap = (m) => Math.max(0, Math.min(DAY_MIN - SNAP_MIN, Math.round(m / SNAP_MIN) * SNAP_MIN))
const hhmm = (m) =>
  `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
const durText = (m) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`)
const shiftDay = (iso, delta) => {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + delta)
  return d.toLocaleDateString('sv-SE')
}
const weekdayName = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })
const monthName = (iso) =>
  new Date(`${iso}T12:00:00`)
    .toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
    .toUpperCase()

/** The day as an instrument reads it: Sun 20 Sep. Order is fixed rather than left to the
 *  locale, because the header's shape is the point; the names still come from the locale. */
const shortDate = (iso) => {
  const d = new Date(`${iso}T12:00:00`)
  const weekday = d.toLocaleDateString(undefined, { weekday: 'short' })
  const month = d.toLocaleDateString(undefined, { month: 'short' })
  return `${weekday} ${d.getDate()} ${month}`
}

/* The app tells the time one way everywhere: 24 hours, mono, tabular. It was mixed before
   (12-hour in the list, 24-hour on the timeline), and two formats for one day is exactly the
   kind of detail that makes a planner feel assembled rather than designed. */

// Week strip helpers
const dowOf = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'narrow' })
const dayNumOf = (iso) => Number(iso.slice(8, 10))

/** The stretches of the day that are spoken for, with overlaps merged.
 *
 * Comparing each block with only the one before it is not enough: a block nested
 * inside another has an end time earlier than its parent's, so the "gap" that follows
 * it is time that is already taken. Merging first is what stops a busy afternoon being
 * described as free. */
const occupied = (blocks) => {
  const spans = blocks
    .filter((b) => b.start_min != null && b.duration_min > 0)
    .map((b) => ({ from: b.start_min, to: b.start_min + b.duration_min }))
    .sort((a, b) => a.from - b.from)

  const merged = []
  for (const span of spans) {
    const last = merged[merged.length - 1]
    if (last && span.from <= last.to) {
      // Overlapping, nested or touching: one stretch, ending at the later end.
      if (span.to > last.to) last.to = span.to
    } else {
      merged.push({ ...span })
    }
  }
  return merged
}

/** How much of the day is spoken for. An overlap is not two hours of your life. */
const busyMinutes = (blocks) =>
  occupied(blocks).reduce((total, span) => total + (span.to - span.from), 0)

/** The visible "free time" bands between blocks.
 *  Internal gaps only: the space before the first block and after the last one is
 *  already reported by the day's tally, and a night-long band would be noise. */
const freeGaps = (blocks, minMinutes = 45) => {
  const merged = occupied(blocks)
  const gaps = []
  for (let i = 1; i < merged.length; i += 1) {
    const from = merged[i - 1].to
    const to = merged[i].from
    if (to - from >= minMinutes) gaps.push({ start_min: from, minutes: to - from })
  }
  return gaps
}

export {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, hhmm, durText, shiftDay,
  weekdayName, monthName, shortDate, dowOf, dayNumOf, freeGaps, occupied, busyMinutes,
}
