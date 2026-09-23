/** Unit tests for where a checklist lives and what the list edits do.
 *  Run: cd frontend && npm test
 *
 *  The thing worth pinning down is `whereSteps`, because it is the one place the three shapes
 *  are told apart, and getting it wrong sends a tick to the wrong route: a line of a routine
 *  written to as if it were a block would be a 404, and a rule's step treated as tickable would
 *  be a checkbox that writes nothing. The list edits are here for the smaller reason: a template
 *  item's steps are positional until they are saved, and a rename that reordered them would be
 *  a change nobody asked for.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  NEW_STEP, changeStep, hasSteps, namesEveryStep, payloadSteps, stepsOf, whereSteps, withStep,
  withoutStep,
} from './subtasks.js'

const task = (extra = {}) => ({
  kind: 'block',
  block: { id: 'b1', title: 'Pack for the trip', day: '2026-09-21', source: 'block', ...extra },
})

const occurrence = {
  kind: 'block',
  block: {
    id: 'routine:r1:2026-09-21',
    title: 'Gym',
    source: 'routine',
    routine_id: 'r1',
    day: '2026-09-21',
    occurrence_day: '2026-09-21',
  },
}

const rule = { kind: 'routine', routine: { id: 'r1', title: 'Gym' } }

test('a holder with no steps is an empty list, not undefined', () => {
  assert.deepEqual(stepsOf({}), [])
  assert.deepEqual(stepsOf(null), [])
  assert.deepEqual(stepsOf({ subtasks: null }), [])
  assert.equal(hasSteps({}), false)
  assert.equal(hasSteps({ subtasks: [] }), false)
  assert.equal(hasSteps({ subtasks: [{ id: 's1', title: 'Passport' }] }), true)
})

test('a task holds its own lines, and a tick goes to the line', () => {
  assert.deepEqual(whereSteps(task()), {
    kind: 'block', blockId: 'b1', day: '2026-09-21', tickable: true,
  })
  assert.equal(whereSteps(null), null)
  assert.equal(whereSteps({ kind: 'block', block: null }), null)
})

test('a day of a routine ticks on the day, not on the rule', () => {
  // The day, not the block's own id: an occurrence has no row, and the tick is written to the
  // override for (rule, day). A route built from the block id would be a 404.
  assert.deepEqual(whereSteps(occurrence), {
    kind: 'occurrence', routineId: 'r1', day: '2026-09-21', tickable: true,
  })
})

test('a day of a routine on another day ticks on that day', () => {
  const other = {
    kind: 'block',
    block: { ...occurrence.block, day: '2026-09-22', occurrence_day: '2026-09-22' },
  }
  assert.equal(whereSteps(other).day, '2026-09-22')
})

test('a rule holds definitions, and nothing about a rule can be ticked', () => {
  const where = whereSteps(rule)
  assert.deepEqual(where, { kind: 'routine', routineId: 'r1', day: null, tickable: false })
  assert.equal(whereSteps({ kind: 'routine', routine: null }), null)
})

test('a step added to a template item goes on the end, and the list is not shared', () => {
  const steps = [{ title: 'Passport' }]
  const next = withStep(steps)
  assert.deepEqual(next.map((s) => s.title), ['Passport', NEW_STEP.title])
  assert.equal(steps.length, 1, 'the list it was given was changed')
})

test('renaming a step keeps every other step where it was', () => {
  const steps = [{ title: 'Passport' }, { title: 'Charger' }, { title: 'Meds' }]
  const next = changeStep(steps, 1, 'Charger and cable')
  assert.deepEqual(next.map((s) => s.title), ['Passport', 'Charger and cable', 'Meds'])
  assert.deepEqual(steps.map((s) => s.title), ['Passport', 'Charger', 'Meds'])
})

test('taking a step out leaves the rest in order', () => {
  const steps = [{ title: 'a' }, { title: 'b' }, { title: 'c' }]
  assert.deepEqual(withoutStep(steps, 1).map((s) => s.title), ['a', 'c'])
  assert.deepEqual(withoutStep(steps, 0).map((s) => s.title), ['b', 'c'])
  assert.deepEqual(withoutStep(steps, 5).map((s) => s.title), ['a', 'b', 'c'])
})

test('a step is sent as a name and nothing else', () => {
  // Ids and sort_order are the server's to assign, and a step has no hour or colour of its own:
  // sending back what the server handed over would be this module claiming to know the order.
  assert.deepEqual(
    payloadSteps([{ id: 's1', title: '  Passport ', sort_order: 3, duration_min: 5 }]),
    [{ title: 'Passport' }],
  )
})

test('a blank step name is a save the panel holds rather than sends', () => {
  assert.equal(namesEveryStep([{ title: 'Passport' }, { title: 'Charger' }]), true)
  assert.equal(namesEveryStep([{ title: 'Passport' }, { title: '   ' }]), false)
  assert.equal(namesEveryStep([]), true)
})
