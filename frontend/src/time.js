const HOUR_PX = 56
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
const dayLabel = (iso, today) => {
  if (iso === today) return 'Today'
  if (iso === shiftDay(today, 1)) return 'Tomorrow'
  if (iso === shiftDay(today, -1)) return 'Yesterday'
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
}

// Week strip helpers
const dowOf = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'narrow' })
const dayNumOf = (iso) => Number(iso.slice(8, 10))

/** The visible "free time" bands between blocks.
 *  Internal gaps only: the space before the first block and after the last one is
 *  already reported by the day's tally, and a night-long band would be noise. */
const freeGaps = (blocks, minMinutes = 45) => {
  const sorted = [...blocks].sort((a, b) => a.start_min - b.start_min)
  const gaps = []
  for (let i = 1; i < sorted.length; i += 1) {
    const from = sorted[i - 1].start_min + sorted[i - 1].duration_min
    const to = sorted[i].start_min
    if (to - from >= minMinutes) gaps.push({ start_min: from, minutes: to - from })
  }
  return gaps
}

export {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, hhmm, durText, shiftDay, dayLabel,
  dowOf, dayNumOf, freeGaps,
}
