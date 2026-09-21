/** Unit tests for the one line at the top of the plan.
 *  Run: cd frontend && npm test
 *
 * The edges are the whole point. "Now" is a half-open interval — current at the starting minute,
 * over at the ending minute — and getting that wrong by one minute means the app claims you are
 * in a block you have finished, or misses the one you just started. Everything else here is about
 * refusing to guess: finished work is not now, untimed work is not now, and a day with nothing
 * left says nothing at all rather than announcing an empty page.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { glanceAt } from './glance.js'

const b = (start, dur, more = {}) => ({
  id: `b${start}`,
  title: `Block at ${start}`,
  start_min: start,
  duration_min: dur,
  done: false,
  ...more,
})

const WORK = b(9 * 60, 90, { title: 'Write the thing' })
const STANDUP = b(11 * 60 + 30, 15, { title: 'Standup' })

test('a block you are inside is what is happening, with the time it ends', () => {
  assert.deepEqual(glanceAt([WORK], 10 * 60), {
    kind: 'now',
    title: 'Write the thing',
    when: 'until 10:30',
    left: '30m left',
  })
})

test('the minute a block starts, it has started', () => {
  const seen = glanceAt([WORK], 9 * 60)
  assert.equal(seen.kind, 'now')
  assert.equal(seen.left, '1h 30m left')
})

test('the minute a block ends, it is over', () => {
  assert.equal(glanceAt([WORK], 10 * 60 + 30), null)
})

test('between blocks, the next one is named rather than the one that ended', () => {
  assert.deepEqual(glanceAt([WORK, STANDUP], 10 * 60 + 30), {
    kind: 'next',
    title: 'Standup',
    when: 'at 11:30',
    left: 'in 1h',
  })
})

test('a block starting exactly now is now, not next', () => {
  const seen = glanceAt([b(10 * 60, 60)], 10 * 60)
  assert.equal(seen.kind, 'now')
  assert.equal(seen.left, '1h left')
})

test('finished work is never now: the block you ticked off is behind you', () => {
  const seen = glanceAt([b(9 * 60, 90, { done: true }), STANDUP], 10 * 60)
  assert.equal(seen.kind, 'next')
  assert.equal(seen.title, 'Standup')
  assert.equal(seen.left, 'in 1h 30m')
})

test('finished work is not next either — a crossed-off block is not coming back', () => {
  const seen = glanceAt([b(11 * 60 + 30, 15, { done: true })], 10 * 60)
  assert.equal(seen, null)
})

test('untimed work is never now: "anytime" has no hour to be in', () => {
  assert.equal(glanceAt([b(null, 0, { title: 'Read the manual' })], 10 * 60), null)
})

test('untimed work alongside timed work does not become the next thing', () => {
  const seen = glanceAt([b(null, 0, { title: 'Read the manual' }), STANDUP], 10 * 60)
  assert.equal(seen.title, 'Standup')
})

test('the order they arrive in does not decide it — the clock does', () => {
  const seen = glanceAt([STANDUP, WORK], 10 * 60)
  assert.equal(seen.title, 'Write the thing')
})

test('two overlapping blocks: the one that started first is the one you are in', () => {
  const seen = glanceAt([b(9 * 60 + 30, 30, { title: 'Second' }), b(9 * 60, 120, { title: 'First' })], 9 * 60 + 45)
  assert.equal(seen.title, 'First')
})

test('nothing timed is running and none is coming: the line says nothing', () => {
  assert.equal(glanceAt([], 10 * 60), null)
  assert.equal(glanceAt([WORK], 23 * 60), null)
})

test('the answer does not reorder the list it was handed', () => {
  const blocks = [STANDUP, WORK]
  glanceAt(blocks, 10 * 60)
  assert.deepEqual(blocks.map((x) => x.title), ['Standup', 'Write the thing'])
})
