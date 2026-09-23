/** Unit tests for the template words and the list edits. Run: cd frontend && npm test
 *
 *  Two things are worth pinning down here. The first is that an item with no hour is never
 *  described as a time: "Anytime" staying out of the span is the difference between a template
 *  that reads true and one that claims a midnight block. The second is that the body sent to
 *  the API is the lines and nothing else — ids and sort_order are the server's, and a payload
 *  that carried them back would be this module claiming to have assigned them.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canApply, describeApply, describeTemplate, payloadItems, plannedTime, reorder, timeSpan,
  withItem, withoutItem,
} from './templates.js'

const item = (title, start_min, duration_min = 30, extra = {}) => ({
  id: `id-${title}`, title, start_min, duration_min, color: 'slate', icon: '', notes: '',
  sort_order: 0, ...extra,
})

const tpl = (name, items) => ({ id: `t-${name}`, name, items })

test('a template with no lines says so, plainly', () => {
  assert.equal(describeTemplate(tpl('Travel day', [])), 'Nothing in it yet')
  assert.equal(describeTemplate(null), 'Nothing in it yet')
  assert.equal(canApply(tpl('Travel day', [])), false)
})

test('the plan reads as a count, its hours, what waits in Anytime and its length', () => {
  const workday = tpl('Workday', [
    item('Gym', 390, 60),
    item('Commute', 480, 30),
    item('Lunch', 720, 30),
    item('Admin', 960, 45),
  ])
  assert.equal(describeTemplate(workday), '4 items · 06:30–16:00 · 2h 45m')
  assert.equal(canApply(workday), true)
})

test('Anytime is not rendered as an hour, and does not invent one', () => {
  const reset = tpl('Weekend reset', [item('Sheets', null, 20), item('Bins', null, 15)])
  assert.equal(timeSpan(reset.items), '', 'a plan with no hours claimed a time range')
  assert.equal(describeTemplate(reset), '2 items · 2 anytime · 35m')

  // Mixed: the span is the hours that exist, and the count of the rest is said separately.
  const mixed = tpl('mixed', [item('Gym', 390, 60), item('Sheets', null, 20)])
  assert.equal(describeTemplate(mixed), '2 items · 06:30–06:30 · 1 anytime · 1h 20m')
  assert.equal(plannedTime([item('Long', 600, 150)]), '2h 30m')
})

test('one item is one item, and gets its own summary', () => {
  assert.equal(describeTemplate(tpl('one', [item('Gym', 390, 60)])), '1 item · 06:30–06:30 · 1h')
})

test('a line can be moved, and the ends are not a special case', () => {
  const lines = [item('A', 600), item('B', 660), item('C', 720)]
  assert.deepEqual(reorder(lines, 2, 0).map((i) => i.title), ['C', 'A', 'B'])
  assert.deepEqual(reorder(lines, 0, 2).map((i) => i.title), ['B', 'C', 'A'])
  assert.equal(reorder(lines, 0, 0), lines, 'a move to where it already was rewrote the list')
  assert.equal(reorder(lines, 0, 3), lines, 'a move off the end should be the list back')
  assert.equal(reorder(lines, -1, 0), lines)
})

test('a line can be taken out by position, and added at the end', () => {
  const lines = [item('A', 600), item('B', null), item('C', 720)]
  assert.deepEqual(withoutItem(lines, 1).map((i) => i.title), ['A', 'C'])
  assert.deepEqual(lines.map((i) => i.title), ['A', 'B', 'C'], 'the list was edited in place')

  const added = withItem(lines)
  assert.equal(added.length, 4)
  assert.equal(added[3].start_min, null, 'a new line should not claim an hour')
  assert.notEqual(added[3], lines[0], 'the new line should be its own object')
})

test('the body sent to the API is the lines, and nothing the server owns', () => {
  const body = payloadItems([item('Gym', null, 60, { icon: '', notes: 'shoes' })])
  assert.deepEqual(body, [
    {
      title: 'Gym', start_min: null, duration_min: 60, color: 'slate', icon: '', notes: 'shoes',
      subtasks: [],
    },
  ])
  assert.deepEqual(Object.keys(body[0]).sort(), [
    'color', 'duration_min', 'icon', 'notes', 'start_min', 'subtasks', 'title',
  ])
  // An hour that is 0 — midnight — is a time, and must not be mistaken for absent.
  assert.equal(payloadItems([item('Midnight', 0, 30)])[0].start_min, 0)
})

test('a line keeps its steps when the list is saved', () => {
  // The whole list is replaced on every save, so a step left out of this body is a step deleted.
  // A line's steps are names in order; ids and the order are the server's to assign.
  const packed = item('Pack for the trip', 540, 30, {
    subtasks: [{ id: 's1', title: 'Passport', sort_order: 0 }, { id: 's2', title: 'Charger' }],
  })
  const body = payloadItems([packed])
  assert.deepEqual(body[0].subtasks, [{ title: 'Passport' }, { title: 'Charger' }])
  assert.deepEqual(payloadItems([item('Gym', null, 60)])[0].subtasks, [])
})

test('applying is described by what it did', () => {
  assert.equal(describeApply({ name: 'Workday', created: ['a', 'b', 'c', 'd'] }),
    '4 blocks added from Workday.')
  assert.equal(describeApply({ name: 'Weekend reset', created: ['a'] }),
    '1 block added from Weekend reset.')
  assert.equal(describeApply({ name: 'Empty', created: [] }), 'Nothing was added.')
  assert.equal(describeApply(null), 'Nothing was added.')
})
