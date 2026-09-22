/** Unit tests for the local half of a repeat.
 *  Run: cd frontend && npm test
 *
 * What is worth pinning here is the numbering and the two facts the editor routes a write by.
 * The rule that decides which days a routine lands on is the server's, and testing it here would
 * be testing a second copy of it — the copy that drifts.
 *
 * The weekday numbering is the one that actually bites: JavaScript counts Sunday as 0 and the API
 * counts Monday as 1, so a single missing conversion puts "every week" on the wrong day and the
 * mistake looks like a bug in the calendar rather than in an index.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  REPEATS,
  WEEKDAY_LABELS,
  differsFromRoutine,
  everyWeeks,
  isOccurrence,
  isoWeekday,
  occurrenceOf,
  toggleWeekday,
  weekdaysFor,
} from './routines.js'

test('the seven labels are a week, and there are seven of them', () => {
  assert.equal(WEEKDAY_LABELS.length, 7)
  assert.equal(WEEKDAY_LABELS.join(''), 'MTWTFSS')
})

test('the options are the six the plan names, Never first', () => {
  assert.deepEqual(
    ['Never', ...REPEATS.map((r) => r.label)].map((l) => l.split(' ')[0]),
    ['Never', 'Every', 'Weekdays', 'Weekends', 'Every', 'Custom'],
  )
})

test('ISO weekday: Monday is 1 and Sunday is 7', () => {
  assert.equal(isoWeekday('2027-03-08'), 1) // Monday
  assert.equal(isoWeekday('2027-03-13'), 6) // Saturday
  assert.equal(isoWeekday('2027-03-14'), 7) // Sunday — the one the 0-based count gets wrong
})

test('every day of one week is numbered in order, with no gaps and no repeats', () => {
  const week = ['08', '09', '10', '11', '12', '13', '14'].map((d) => isoWeekday(`2027-03-${d}`))
  assert.deepEqual(week, [1, 2, 3, 4, 5, 6, 7])
})

test('choosing "every week" starts from the day you are looking at', () => {
  assert.deepEqual(weekdaysFor('weekly_interval', '2027-03-13'), [6])
})

test('choosing the other rules does not pretend to pick days for you', () => {
  assert.deepEqual(weekdaysFor('daily', '2027-03-13'), [])
  assert.deepEqual(weekdaysFor('weekdays', '2027-03-13'), [])
  assert.deepEqual(weekdaysFor('selected_weekdays', '2027-03-13'), [])
})

test('tapping a day adds it, tapping it again takes it away', () => {
  assert.deepEqual(toggleWeekday([], 3), [3])
  assert.deepEqual(toggleWeekday([3], 3), [])
  assert.deepEqual(toggleWeekday([5], 1), [1, 5], 'added days stay in order')
  assert.deepEqual(toggleWeekday([1, 3, 5], 3), [1, 5])
})

test('a day cannot be added twice', () => {
  assert.deepEqual(toggleWeekday([1, 3], 3), [1])
  assert.deepEqual(toggleWeekday(toggleWeekday([1, 3], 3), 3), [1, 3])
})

test('the wording follows the number, and stops pretending at one', () => {
  assert.equal(everyWeeks(1), 'Every week')
  assert.equal(everyWeeks(2), 'Every 2 weeks')
  assert.equal(everyWeeks(), 'Every week')
})

test('an occurrence is told apart by what the API says it is, not by the shape of it', () => {
  const occurrence = {
    id: 'routine:abc:2027-03-08',
    source: 'routine',
    routine_id: 'abc',
    occurrence_day: '2027-03-08',
    day: '2027-03-08',
  }
  assert.equal(isOccurrence(occurrence), true)
  assert.deepEqual(occurrenceOf(occurrence), { routine_id: 'abc', day: '2027-03-08' })

  const block = { id: 'deadbeef1234', source: 'block', day: '2027-03-08' }
  assert.equal(isOccurrence(block), false)
  assert.deepEqual(occurrenceOf(block), { routine_id: null, day: null })
  assert.deepEqual(occurrenceOf(null), { routine_id: null, day: null })
})

test('a day that matches its routine has nothing to undo', () => {
  const routine = {
    id: 'abc', title: 'Gym', start_min: 390, duration_min: 60, color: 'teal', icon: '', notes: '',
  }
  const plain = { ...routine, source: 'routine', routine_id: 'abc', day: '2027-03-08' }
  assert.equal(differsFromRoutine(plain, routine), false)

  assert.equal(differsFromRoutine({ ...plain, start_min: 420 }, routine), true)
  assert.equal(differsFromRoutine({ ...plain, title: 'Swim' }, routine), true)
  assert.equal(differsFromRoutine({ ...plain, notes: 'the 6am class' }, routine), true)
  assert.equal(differsFromRoutine(plain, null), false)
  assert.equal(differsFromRoutine(null, routine), false)
})

test('a field the routine does not have does not count as a difference', () => {
  // `done` and the ids are not fields of the rule, and a day being finished is not a day that
  // has been edited — offering "put it back" for a ticked-off occurrence would be a lie.
  const routine = {
    id: 'abc', title: 'Gym', start_min: 390, duration_min: 60, color: 'teal', icon: '', notes: '',
  }
  const block = {
    ...routine, source: 'routine', routine_id: 'abc', day: '2027-03-08',
    id: 'routine:abc:2027-03-08', done: true, updated_at: 'whenever',
  }
  assert.equal(differsFromRoutine(block, routine), false)
})
