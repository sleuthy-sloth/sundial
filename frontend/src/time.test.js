/** Unit tests for the day arithmetic. Run: cd frontend && npm test
 *
 * The case worth pinning down is the nested one: a block inside another must not leave
 * a "free" band behind it, which is what comparing each block with only the one before
 * it did. A busy afternoon must never be described as free time.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { busyMinutes, freeGaps, occupied } from './time.js'

const at = (start, duration) => ({ start_min: start, duration_min: duration })
const sum = (blocks) => blocks.reduce((n, b) => n + b.duration_min, 0)

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
