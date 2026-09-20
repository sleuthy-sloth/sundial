/** Which part of the day a block belongs to, and the sections in order.
 *
 *  The window starts at 05:00 rather than midnight: something at 1am belongs with
 *  the evening you were still in, not with the morning you have not reached. */
const SECTIONS = [
  { key: 'anytime', label: 'Anytime', glyph: 'clock' },
  { key: 'morning', label: 'Morning', glyph: 'sunrise' },
  { key: 'afternoon', label: 'Afternoon', glyph: 'sun' },
  { key: 'evening', label: 'Evening', glyph: 'moon' },
]

const DAY_START = 5 * 60
const AFTERNOON = 12 * 60
const EVENING = 17 * 60

const bucketOf = (startMin) => {
  if (startMin < DAY_START) return 'evening'
  if (startMin < AFTERNOON) return 'morning'
  if (startMin < EVENING) return 'afternoon'
  return 'evening'
}

/** Anything unscheduled is "Anytime" — the inbox, in Tiimo's language. */
function buildAgenda(blocks, inbox) {
  const buckets = { anytime: [...inbox], morning: [], afternoon: [], evening: [] }
  for (const b of [...blocks].sort((x, y) => x.start_min - y.start_min)) {
    buckets[bucketOf(b.start_min)].push(b)
  }
  return SECTIONS.map((s) => ({ ...s, items: buckets[s.key] }))
}

export { SECTIONS, bucketOf, buildAgenda }
