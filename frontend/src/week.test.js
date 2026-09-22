/** Unit tests for the week arithmetic. Run: cd frontend && npm test
 *
 *  Two things here are load-bearing. The week is Monday-first by decision rather than by
 *  locale, so a Sunday must belong to the week that started six days earlier — the classic
 *  off-by-one, and the one that silently shows the wrong seven days rather than failing. And
 *  the bar's three widths have to add up to the busy time exactly, because the alternative
 *  draws a shared hour twice and a bar that is longer than the day it describes.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { barOf, compact, daySentence, emptyDay, shortDow, weekDays, weekStart, weekTitle } from './week.js'

// The month names come from the locale and their lengths vary (en-US "Sep", en-GB "Sept"), so
// the expected strings are built from the same call the app makes rather than typed out.
const month = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: 'short' })

test('the week starts on Monday, and Sunday belongs to the week before it', () => {
  assert.equal(weekStart('2026-09-21'), '2026-09-21') // a Monday is its own week's first day
  assert.equal(weekStart('2026-09-22'), '2026-09-21')
  assert.equal(weekStart('2026-09-26'), '2026-09-21') // Saturday
  assert.equal(weekStart('2026-09-27'), '2026-09-21') // Sunday, six days after that Monday
  assert.equal(weekStart('2026-09-28'), '2026-09-28') // and the next Monday starts a new week
})

test('a week that begins in the month before still begins on its Monday', () => {
  assert.equal(weekStart('2026-09-01'), '2026-08-31')
  assert.equal(weekStart('2026-09-06'), '2026-08-31')
  assert.equal(weekStart('2026-09-07'), '2026-09-07')
})

test('the seven days are consecutive and start with the Monday', () => {
  const days = weekDays('2026-09-24')
  assert.equal(days.length, 7)
  assert.equal(days[0], '2026-09-21')
  assert.equal(days[6], '2026-09-27')
  assert.deepEqual(days, [
    '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25', '2026-09-26', '2026-09-27',
  ])
})

test('a week crossing a month and a year boundary lists both sides of it', () => {
  const days = weekDays('2027-01-01')
  assert.equal(days[0], '2026-12-28')
  assert.equal(days[6], '2027-01-03')
  assert.equal(new Set(days).size, 7, 'and no day twice')
})

test('the heading names the month once when the week stays in it, twice when it does not', () => {
  assert.equal(weekTitle('2026-09-21'), `21 ${month('2026-09-21')} – 27`)
  assert.equal(weekTitle('2026-09-27'), `21 ${month('2026-09-21')} – 27`)
  // A week that crosses a month but not a year names both months and neither year.
  assert.equal(weekTitle('2026-09-30'), `28 ${month('2026-09-28')} – 4 ${month('2026-10-04')}`)
  // One that crosses the year needs both, or "28 Dec – 3 Jan" is a week nobody can place.
  assert.equal(
    weekTitle('2027-01-01'),
    `28 ${month('2026-12-28')} 2026 – 3 ${month('2027-01-03')} 2027`,
  )
  assert.equal(weekTitle('2026-12-30'), `28 ${month('2026-12-28')} 2026 – 3 ${month('2027-01-03')} 2027`)
})

test('a column heading is three letters, not the ambiguous one', () => {
  const monday = shortDow('2026-09-21')
  assert.match(monday, /^[A-Za-z]{3,4}$/, monday)
  assert.notEqual(shortDow('2026-09-22'), shortDow('2026-09-24'), 'Tuesday is not Thursday')
  assert.notEqual(shortDow('2026-09-26'), shortDow('2026-09-27'), 'and neither weekend day repeats')
})

test('a duration is written the way a narrow column can hold it', () => {
  assert.equal(compact(0), '—')
  assert.equal(compact(45), '45m')
  assert.equal(compact(60), '1h')
  assert.equal(compact(260), '4h20') // the plan's own sketch: 4h20 for a Monday
  assert.equal(compact(600), '10h')
  assert.equal(compact(1440), '24h')
  assert.equal(compact(65), '1h05')
})

test('a negative or missing figure is nothing rather than a negative bar', () => {
  assert.equal(compact(undefined), '—')
  assert.equal(compact(-30), '—')
})

test('the bar is the plan, the calendar, and the hour they share — counted once', () => {
  // 09:00–11:00 planned (120), 10:00–11:00 on the calendar (60), 10:00–11:00 shared (60),
  // so the day is busy for 120 minutes and open for 1320.
  const bar = barOf({ planned_minutes: 120, calendar_busy_minutes: 60, open_minutes: 1320 })
  assert.equal(bar.busy, 120)
  assert.equal(bar.plan, `${(60 / 1440) * 100}%`)
  assert.equal(bar.both, `${(60 / 1440) * 100}%`)
  assert.equal(bar.calendar, '0%')
  assert.equal(bar.planned, 120)
  assert.equal(bar.calendar_minutes, 60)
})

test('the three widths are the busy time, not the two totals added up', () => {
  const covered = (day) => {
    const bar = barOf(day)
    return Number.parseFloat(bar.plan) + Number.parseFloat(bar.both) + Number.parseFloat(bar.calendar)
  }
  const near = (left, right) => Math.abs(left - right) < 1e-9
  // A day 120 minutes busy: whatever the split, the bar covers 120 minutes of the 1440.
  assert.ok(near(covered({ planned_minutes: 120, calendar_busy_minutes: 0, open_minutes: 1320 }), (120 / 1440) * 100))
  // The same day with an appointment sharing half of it: still 120.
  assert.ok(near(covered({ planned_minutes: 120, calendar_busy_minutes: 60, open_minutes: 1320 }), (120 / 1440) * 100))
  // And a day that is only the calendar's.
  assert.ok(near(covered({ planned_minutes: 0, calendar_busy_minutes: 60, open_minutes: 1380 }), (60 / 1440) * 100))
})

test('a full day fills the whole bar and leaves none of it open', () => {
  const bar = barOf({ planned_minutes: 1440, calendar_busy_minutes: 0, open_minutes: 0 })
  assert.equal(Number.parseFloat(bar.plan), 100)
  assert.equal(bar.busy, 1440)
})

test('an empty day has no bar at all', () => {
  const bar = barOf(emptyDay('2026-09-21'))
  assert.equal(bar.busy, 0)
  assert.equal(Number.parseFloat(bar.plan) + Number.parseFloat(bar.both) + Number.parseFloat(bar.calendar), 0)
})

test('a day with nothing in it is a full day, open', () => {
  assert.deepEqual(emptyDay('2026-09-21'), {
    day: '2026-09-21',
    planned_minutes: 0,
    open_minutes: 1440,
    block_count: 0,
    completed_count: 0,
    calendar_busy_minutes: 0,
  })
})

test('a day column reads as a sentence, and says nothing about being behind', () => {
  const named = new Date('2026-09-21T12:00:00').toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long',
  })
  const said = daySentence(
    { day: '2026-09-21', planned_minutes: 260, open_minutes: 1180, block_count: 3, completed_count: 1, calendar_busy_minutes: 0 },
    '2026-09-21',
  )
  assert.ok(said.startsWith(`${named}: `), said)
  assert.match(said, /4h 20m planned/)
  assert.match(said, /19h 40m open/)
  assert.match(said, /3 blocks/)
  assert.match(said, /1 done/)
  assert.match(said, /today$/)
  assert.doesNotMatch(said, /overdue|late|missed|behind|left to do/i)
})

test('an empty day says so quietly, and is not today when it is not', () => {
  const said = daySentence(emptyDay('2026-09-22'), '2026-09-21')
  assert.match(said, /nothing planned/)
  assert.match(said, /24h open/)
  assert.doesNotMatch(said, /today/)
  assert.doesNotMatch(said, /blocks|done/)
})
