/**
 * Unit tests for what happens to work left on yesterday.
 * Run: cd frontend && npm test
 *
 * The decisions under test are the ones that decide whether anything is written to a day you have
 * already had, so the refusals carry the weight here: an unrecognised setting must not move
 * anything, an empty list must not draw a section, and a "leave there" must not outlive the day it
 * was about.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  ROLLOVER_DEFAULT,
  ROLLOVER_OPTIONS,
  dismissed,
  dismissedKey,
  leaveThere,
  rolloverAction,
  stillWaiting,
} from './rollover.js'

const SETTINGS_PY = new URL('../../backend/services/settings.py', import.meta.url)
const TODAY = '2026-09-22'
const TOMORROW = '2026-09-23'
const block = (id, title = 'Laundry') => ({ id, title, source: 'block', done: false })

/** A sessionStorage that is only as good as this file needs, and can be taken away again. */
function withStorage(run) {
  const held = new Map()
  globalThis.sessionStorage = {
    getItem: (key) => (held.has(key) ? held.get(key) : null),
    setItem: (key, value) => held.set(key, String(value)),
  }
  try {
    return run(held)
  } finally {
    delete globalThis.sessionStorage
  }
}

test('the three answers are the plan\u2019s three, in the plan\u2019s order', () => {
  assert.deepEqual(
    ROLLOVER_OPTIONS.map((o) => o.label),
    ['Ask me the next day', 'Move to Anytime automatically', 'Leave on the original day'],
  )
  assert.equal(ROLLOVER_DEFAULT, ROLLOVER_OPTIONS[0].value, 'the first offered is the default')
})

test('nothing left means nothing happens, whatever the setting says', () => {
  for (const setting of ['ask', 'anytime', 'leave', undefined]) {
    assert.equal(rolloverAction(setting, []), 'nothing', String(setting))
  }
})

test('asking, moving and leaving are the three answers to work being left', () => {
  const waiting = [block('a')]
  assert.equal(rolloverAction('ask', waiting), 'ask')
  assert.equal(rolloverAction('anytime', waiting), 'move')
  assert.equal(rolloverAction('leave', waiting), 'nothing')
})

test('a setting this build does not know asks rather than moving anything', () => {
  // Both answers are wrong about a fourth option that some later build knows. Only one of them
  // writes to a day you have already had, and it is not this one.
  assert.equal(rolloverAction('summarise it with an llm', [block('a')]), 'ask')
})

test('a dismissed item leaves the section and the others stay', () => {
  const waiting = [block('a'), block('b'), block('c')]
  assert.deepEqual(stillWaiting(waiting, ['b']).map((b) => b.id), ['a', 'c'])
  assert.deepEqual(stillWaiting(waiting, []).map((b) => b.id), ['a', 'b', 'c'])
  assert.deepEqual(stillWaiting([], ['a']), [])
  assert.deepEqual(stillWaiting(undefined, undefined), [])
})

test('leaving one alone is remembered for this tab, once', () => {
  withStorage(() => {
    assert.deepEqual(dismissed(TODAY), [], 'nothing has been left alone yet')
    assert.deepEqual(leaveThere(TODAY, 'a'), ['a'])
    assert.deepEqual(leaveThere(TODAY, 'b'), ['a', 'b'])
    assert.deepEqual(leaveThere(TODAY, 'a'), ['a', 'b'], 'the same one twice is still one')
    assert.deepEqual(dismissed(TODAY), ['a', 'b'], 'and it is still there on the next look')
  })
})

test('a day\u2019s dismissals cannot hide another day\u2019s work', () => {
  // The point of putting the day in the key. A block left alone yesterday that is STILL there today
  // is a block nobody has dealt with, and hiding it would be the app quietly giving up on it.
  withStorage(() => {
    leaveThere(TODAY, 'a')
    assert.deepEqual(dismissed(TOMORROW), [])
    assert.notEqual(dismissedKey(TODAY), dismissedKey(TOMORROW))
  })
})

test('with nowhere to keep it, a dismissal is still not a crash', () => {
  // Private modes and locked-down browsers have thrown on sessionStorage before now, and the row is
  // still on yesterday either way: the fallback is being asked about it again.
  assert.deepEqual(dismissed(TODAY), [])
  assert.deepEqual(leaveThere(TODAY, 'a'), ['a'])
  assert.deepEqual(dismissed(TODAY), [], 'kept nowhere, so it does not come back')
})

test('something unreadable where the list should be counts as nothing', () => {
  withStorage((held) => {
    held.set(dismissedKey(TODAY), 'not json at all')
    assert.deepEqual(dismissed(TODAY), [])
    held.set(dismissedKey(TODAY), '{"a": 1}')
    assert.deepEqual(dismissed(TODAY), [], 'an object is not a list of ids')
  })
})

// ---- the contract between this module and the server ---------------------------------------
// Read out of the Python rather than trusted to a comment, the way `datafile.test.js` reads the
// export format: the failure this guards against is silent, and it is a setting the panel offers
// but the API refuses, or one the API offers and the panel cannot name.

test('the option values match ROLLOVER in backend/services/settings.py', () => {
  const src = readFileSync(SETTINGS_PY, 'utf8')
  const tuple = /^ROLLOVER = \(([^)]+)\)$/m.exec(src)?.[1]
  const values = [...(tuple ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
  assert.deepEqual(
    values,
    ROLLOVER_OPTIONS.map((o) => o.value),
    'the values the panel sends should be the values the server stores',
  )
  assert.equal(values[0], ROLLOVER_DEFAULT, 'and both should agree on which one is the default')
})
