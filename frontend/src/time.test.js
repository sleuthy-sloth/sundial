/** Unit tests for the day arithmetic. Run: cd frontend && npm test
 *
 * The case worth pinning down is the nested one: a block inside another must not leave
 * a "free" band behind it, which is what comparing each block with only the one before
 * it did. A busy afternoon must never be described as free time.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { appointments, busyMinutes, freeGaps, occupied, shortDate } from './time.js'

const at = (start, duration) => ({ start_min: start, duration_min: duration })
const sum = (blocks) => blocks.reduce((n, b) => n + b.duration_min, 0)

const DAY = '2026-09-22'
const localISO = (h, m, day = 22) => new Date(2026, 8, day, h, m, 0).toISOString()
const ev = (title, h, m, minutes, extra = {}) => ({
  id: `${title}-${h}${m}`, title, calendar_ref: 'work', all_day: 0,
  start_utc: localISO(h, m), end_utc: localISO(h, m + minutes), ...extra,
})


test('the day reads as an instrument would write it', () => {
  // Order is fixed; the names come from the locale, and its month abbreviations vary in
  // length ("Sep" in en-US, "Sept" in en-GB), so the shape is what is asserted.
  assert.match(shortDate('2026-09-20'), /^[A-Za-z]{3,4} 20 [A-Za-z]{3,4}$/)
  assert.equal(shortDate('2026-09-20'), shortDate('2026-09-20'), 'the same day twice')
  assert.notEqual(shortDate('2026-09-20'), shortDate('2026-09-21'), 'and a different day differs')
})

test('a nested block leaves no free band behind it', () => {
  // 09:00-12:00 with 10:00-10:30 inside it, then 12:00-12:30
  const day = [at(540, 180), at(600, 30), at(720, 30)]

  assert.deepEqual(freeGaps(day, 15), [], 'time already taken was reported as free')
  assert.equal(busyMinutes(day), 210)
  assert.equal(sum(day), 240, 'the blocks still add up to four hours on paper')
})

test('overlapping blocks count once towards the day', () => {
  const day = [at(540, 120), at(600, 120)] // 09:00-11:00 and 10:00-12:00

  assert.equal(busyMinutes(day), 180)
  assert.equal(sum(day), 240)
  assert.deepEqual(occupied(day), [{ from: 540, to: 720 }])
})

test('touching blocks are one stretch, not two', () => {
  assert.deepEqual(occupied([at(540, 60), at(600, 60)]), [{ from: 540, to: 660 }])
  assert.deepEqual(freeGaps([at(540, 60), at(600, 60)], 15), [])
})

test('a real gap is found at the right place and size', () => {
  const day = [at(540, 60), at(720, 30)] // 09:00-10:00, then 12:00-12:30

  assert.deepEqual(freeGaps(day, 45), [{ start_min: 600, minutes: 120 }])
  assert.deepEqual(freeGaps(day, 121), [], 'a gap shorter than the threshold was drawn')
})

test('gaps come out in order, whatever order the blocks arrive in', () => {
  const day = [at(840, 60), at(540, 60), at(660, 60)] // 14:00, 09:00, 11:00

  assert.deepEqual(occupied(day), [
    { from: 540, to: 600 },
    { from: 660, to: 720 },
    { from: 840, to: 900 },
  ])
  assert.deepEqual(freeGaps(day, 30), [
    { start_min: 600, minutes: 60 },
    { start_min: 720, minutes: 120 },
  ])
})

test('an empty day has nothing occupied and nothing free in the middle', () => {
  assert.deepEqual(occupied([]), [])
  assert.deepEqual(freeGaps([]), [])
  assert.equal(busyMinutes([]), 0)
  assert.equal(sum([]), 0)
})

test('a single block has no internal free time', () => {
  const day = [at(540, 600)]

  assert.deepEqual(freeGaps(day, 15), [])
  assert.equal(busyMinutes(day), 600)
})

test('the inbox is not part of the day', () => {
  // An unscheduled block has no start, and must not be counted as time taken.
  const blocks = [at(540, 60), { start_min: null, duration_min: 30 }]

  assert.deepEqual(occupied(blocks), [{ from: 540, to: 600 }])
  assert.equal(busyMinutes(blocks), 60)
})

test('a zero-length block occupies nothing', () => {
  assert.deepEqual(occupied([at(540, 0)]), [])
})

test('a block that swallows the others leaves one stretch', () => {
  const day = [at(480, 300), at(540, 30), at(700, 60)] // 08:00-13:00 contains the middle one

  assert.deepEqual(occupied(day), [{ from: 480, to: 780 }])
  assert.deepEqual(freeGaps(day, 15), [])
  assert.equal(busyMinutes(day), 300)
})


/* ---------------------------------------------------------------- the calendar in the day
 *
 * An appointment is placed by the same rule as a block — where its own clock says — and the one
 * thing the timeline has to know is whether it collides with something planned. Clashing is
 * deliberately NOT the rule `occupied()` uses above: back-to-back blocks are one busy stretch,
 * but an appointment that ends exactly when a block starts is not an over-booked hour, and
 * treating it as one would split the day in half over a coincidence of arithmetic.
 */

test('an appointment is placed where its own clock says', () => {
  const { spans } = appointments([], [ev('Maintenance review', 10, 0, 60)], DAY)

  assert.equal(spans.length, 1)
  assert.equal(spans[0].title, 'Maintenance review')
  assert.equal(spans[0].start_min, 600, '10:00 in local minutes')
  assert.equal(spans[0].minutes, 60)
  assert.equal(spans[0].clash, false, 'nothing planned, nothing to clash with')
})

test('an all-day event has no hour to sit at, so it is not placed', () => {
  const { spans } = appointments([], [ev('Bank holiday', 0, 0, 1440, { all_day: 1 })], DAY)

  assert.deepEqual(spans, [], 'an all-day event was given a row on the clock')
})

test('an appointment running in from yesterday is clamped to the start of the day', () => {
  // 23:30 the night before, ending 00:30 today: a half hour of today, not a negative row.
  const overnight = { id: 'o', title: 'Red-eye', calendar_ref: 'work', all_day: 0,
    start_utc: localISO(23, 30, 21), end_utc: localISO(0, 30, 22) }
  const { spans } = appointments([], [overnight], DAY)

  assert.equal(spans[0].start_min, 0)
  assert.equal(spans[0].minutes, 30)
})

test('an event with no length is not an appointment', () => {
  const empty = { id: 'z', title: 'Nothing', calendar_ref: 'work', all_day: 0,
    start_utc: localISO(9, 0), end_utc: localISO(9, 0) }

  assert.deepEqual(appointments([], [empty], DAY).spans, [])
})

test('touching is not clashing', () => {
  // 09:00-10:00 planned against an appointment starting at 10:00 sharp. occupied() merges
  // these; the layout must not, or every hour that ends when the next begins is "over-booked".
  const day = [at(540, 60)]
  const { spans, squeezed } = appointments(day, [ev('Commander\'s call', 10, 0, 45)], DAY)

  assert.equal(spans[0].clash, false, 'an appointment touching a block was called a clash')
  assert.deepEqual([...squeezed], [], 'the block gave up room to nothing')
})

test('an appointment nested inside a block clashes, and the block gives up the room', () => {
  const day = [{ id: 'deep', start_min: 570, duration_min: 150 }]  // 09:30-12:00
  const { spans, squeezed } = appointments(day, [ev('Maintenance review', 10, 0, 60)], DAY)

  assert.equal(spans[0].clash, true)
  assert.deepEqual([...squeezed], ['deep'], 'the block that overlaps kept the whole column')
})

test('a partial overlap clashes too', () => {
  const day = [{ id: 'pt', start_min: 390, duration_min: 60 }]  // 06:30-07:30
  const { spans, squeezed } = appointments(day, [ev('Dental', 7, 0, 45)], DAY)

  assert.equal(spans[0].clash, true)
  assert.deepEqual([...squeezed], ['pt'])
})

test('blocks the calendar never touches keep the whole column', () => {
  const day = [{ id: 'a', start_min: 390, duration_min: 60 }, { id: 'b', start_min: 840, duration_min: 60 }]
  const { squeezed } = appointments(day, [ev('Dinner', 18, 15, 60)], DAY)

  assert.deepEqual([...squeezed], [], 'a block nowhere near the appointment was squeezed')
})

test('two clashing appointments share the free half instead of covering each other', () => {
  const day = [{ id: 'deep', start_min: 570, duration_min: 150 }]
  const { spans } = appointments(day, [ev('Review', 10, 0, 60), ev('Call', 10, 30, 30)], DAY)

  assert.deepEqual(spans.map((s) => s.clash), [true, true])
  assert.deepEqual(spans.map((s) => s.lane).sort(), [0, 1], 'two appointments landed on one lane')
  assert.deepEqual(spans.map((s) => s.lanes), [2, 2], 'the half was not shared between them')
})

test('one appointment in the free half needs no sharing', () => {
  const day = [{ id: 'deep', start_min: 570, duration_min: 150 }]
  const { spans } = appointments(day, [ev('Review', 10, 0, 60)], DAY)

  assert.equal(spans[0].lanes, 1)
  assert.equal(spans[0].lane, 0)
})

test('an appointment outside the day entirely is dropped, not drawn off the end', () => {
  const other = { id: 'x', title: 'Next week', calendar_ref: 'work', all_day: 0,
    start_utc: localISO(9, 0, 25), end_utc: localISO(10, 0, 25) }
  const { spans } = appointments([], [other], DAY)

  assert.deepEqual(spans, [], 'an appointment on another day was drawn on this one')
})

test('a day with no calendar has no appointments and squeezes nothing', () => {
  const { spans, squeezed } = appointments([at(540, 60)], [], DAY)

  assert.deepEqual(spans, [])
  assert.deepEqual([...squeezed], [])
})
