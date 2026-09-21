/** Unit tests for the pieces that keep editing honest. Run: cd frontend && npm test */

import assert from 'node:assert/strict'
import test from 'node:test'

import { createLatest, createWriteQueue, debounce } from './saving.js'

const settle = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms))

test('writes for one block go out in the order they were asked for', async () => {
  const queue = createWriteQueue()
  const order = []

  const slow = () =>
    new Promise((resolve) =>
      setTimeout(() => {
        order.push('first')
        resolve()
      }, 60),
    )
  const quick = async () => {
    order.push('second')
  }

  const one = queue.run('block-1', slow)
  const two = queue.run('block-1', quick)
  await Promise.all([one, two])

  assert.deepEqual(order, ['first', 'second'])
})

test('a slow write for one block does not hold up another block', async () => {
  const queue = createWriteQueue()
  let held = null

  const blocked = queue.run('block-1', () => new Promise((resolve) => { held = resolve }))
  const other = await queue.run('block-2', async () => 'went through')

  assert.equal(other, 'went through', 'block-2 waited on block-1')
  held()
  await blocked
})

test('a failed write does not stop the next one, but the caller sees it', async () => {
  const queue = createWriteQueue()
  const ran = []

  const failure = queue.run('block-1', async () => {
    throw new Error('the server said no')
  })
  const after = queue.run('block-1', async () => {
    ran.push('second')
    return 'ok'
  })

  await assert.rejects(failure, /the server said no/)
  assert.equal(await after, 'ok')
  assert.deepEqual(ran, ['second'])
})

test('only the newest load is current', () => {
  const latest = createLatest()

  const first = latest.begin()
  assert.ok(latest.isCurrent(first))

  const second = latest.begin()
  assert.ok(latest.isCurrent(second))
  assert.equal(latest.isCurrent(first), false, 'the load you left is still current')
})

test('debounce runs once, with the last arguments', async () => {
  const seen = []
  const save = debounce((value) => seen.push(value), 20)

  save('a')
  save('ab')
  save('abc')
  assert.equal(seen.length, 0, 'it ran before things settled')
  assert.ok(save.pending())

  await settle(60)
  assert.deepEqual(seen, ['abc'])
  assert.equal(save.pending(), false)
})

test('flush sends what is waiting, and sends it only once', async () => {
  const seen = []
  const save = debounce((value) => seen.push(value), 1000)

  save('leaving the field')
  assert.equal(save.pending(), true)
  save.flush()
  assert.deepEqual(seen, ['leaving the field'])

  await settle(30)
  assert.deepEqual(seen, ['leaving the field'], 'the timer fired as well')
  assert.equal(save.pending(), false)
})

test('flush with nothing waiting does nothing', async () => {
  const seen = []
  const save = debounce((value) => seen.push(value), 10)

  save.flush()
  await settle(30)
  assert.deepEqual(seen, [])
})

test('cancel drops what was waiting', async () => {
  const seen = []
  const save = debounce((value) => seen.push(value), 10)

  save('never mind')
  save.cancel()
  await settle(30)

  assert.deepEqual(seen, [])
  assert.equal(save.pending(), false)
})
