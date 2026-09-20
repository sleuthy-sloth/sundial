/**
 * End-to-end check for the timeline: real mouse drags in headless Chromium,
 * then the API is read back to confirm the server agrees with what the UI did.
 *
 * Expectations are derived from the API, never hardcoded, so the check survives
 * whatever is already in the database. It seeds its own data and removes it again.
 *
 *   cd frontend && npm run check:ui
 */
import { createRequire } from 'node:module'

// Playwright lives in frontend/node_modules; this file is run through `node`.
const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const BASE = process.argv[2] || 'http://127.0.0.1:6770'
const HOUR_PX = 56
const SNAP_MIN = 15
const today = new Date().toLocaleDateString('sv-SE')
const EMPTY_DAY = '2099-01-01' // a day nothing will ever be seeded on

let failures = 0
const check = (name, pass, detail = '') => {
  console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
  if (!pass) failures++
}

const req = async (path, init) => {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (res.status === 204) return null
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(`${path}: ${res.status} ${JSON.stringify(body)}`)
  return body
}
const blocksOn = async (day) => (await req(`/day?day=${day}`)).blocks
const inboxNow = async () => (await req('/day')).inbox
const find = async (id) =>
  (await blocksOn(today)).find((b) => b.id === id) || (await inboxNow()).find((b) => b.id === id)
const snapMin = (m) => Math.max(0, Math.min(1440 - SNAP_MIN, Math.round(m / SNAP_MIN) * SNAP_MIN))

const made = []
const spawn = async (body) => {
  const b = await req('/blocks', { method: 'POST', body: JSON.stringify(body) })
  made.push(b.id)
  return b
}

// ---- seed ----
const walk = await spawn({ title: 'ui-check walk', day: today, start_min: 420, duration_min: 60, color: 'emerald' })
const work = await spawn({ title: 'ui-check deep work', day: today, start_min: 600, duration_min: 60, color: 'violet' })
const loose = await spawn({ title: 'ui-check inbox item', duration_min: 30 })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const consoleErrors = []
page.on('pageerror', (e) => consoleErrors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('.content .block')

// ---- what rendered ----
check('24 hour labels drawn', (await page.locator('.hour-label').count()) === 24)
check('the now line is on today', (await page.locator('.now').count()) === 1)
check('day label reads "Today"', (await page.locator('.day-label').innerText()).trim() === 'Today')
check(
  'every block the API returns is on the timeline',
  (await page.locator('.content .block').count()) === (await blocksOn(today)).length,
  `${await page.locator('.content .block').count()} drawn`,
)
check(
  'the inbox shows what the API returns',
  (await page.locator('.inbox .chip').count()) === (await inboxNow()).length,
)

const boxOf = async (text) => {
  const el = page.locator('.content .block').filter({ hasText: text }).first()
  await el.scrollIntoViewIfNeeded()
  return el.boundingBox()
}

// ---- drag a block down two hours: the conversion must be exactly right ----
{
  const box = await boxOf('ui-check walk')
  const x = box.x + box.width / 2
  const y = box.y + 18
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y + 4) // clear the click/drag threshold
  await page.mouse.move(x + 2, y + 2 * HOUR_PX)
  await page.mouse.up()
  await page.waitForTimeout(250)
  const after = await find(walk.id)
  check(
    'dragging down 2h lands exactly 120 minutes later',
    after.start_min === 420 + 120,
    `420 -> ${after.start_min}`,
  )
}

// ---- drag the bottom handle: length changes, start does not ----
{
  const box = await boxOf('ui-check deep work')
  const x = box.x + box.width / 2
  const y = box.y + box.height - 3 // inside the resize handle
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y + 4)
  await page.mouse.move(x, y + HOUR_PX)
  await page.mouse.up()
  await page.waitForTimeout(250)
  const after = await find(work.id)
  check(
    'resizing changes the length and nothing else',
    after.duration_min === 120 && after.start_min === 600,
    `600/${after.duration_min}m`,
  )
}

// ---- drag from the inbox onto the timeline: lands where the pointer is ----
{
  const chip = await page.locator('.inbox .chip').filter({ hasText: 'ui-check inbox item' }).first().boundingBox()
  const content = await page.locator('.content').boundingBox()
  const targetY = Math.min(Math.max(content.y + 60, chip.y), 820)
  const expected = snapMin(((targetY - content.y) / HOUR_PX) * 60)

  await page.mouse.move(chip.x + 30, chip.y + 12)
  await page.mouse.down()
  await page.mouse.move(chip.x + 60, targetY - 20)
  await page.mouse.move(content.x + content.width / 2, targetY)
  await page.mouse.up()
  await page.waitForTimeout(300)

  const after = await find(loose.id)
  check('inbox drag schedules the block', after?.day === today && after?.start_min != null, `day=${after?.day}`)
  check('it lands under the pointer', after?.start_min === expected, `expected ${expected}, got ${after?.start_min}`)
  check('and it left the inbox', (await inboxNow()).every((b) => b.id !== loose.id))
}

// ---- double-click empty timeline creates a block ----
{
  const beforeIds = new Set((await blocksOn(today)).map((b) => b.id))
  const content = await page.locator('.content').boundingBox()
  const y = Math.min(content.y + content.height - 40, 840)
  await page.mouse.dblclick(content.x + content.width / 2, y)
  await page.waitForTimeout(400)
  const created = (await blocksOn(today)).filter((b) => !beforeIds.has(b.id))
  check('double-click adds exactly one block', created.length === 1, `${created.length} new`)
  created.forEach((b) => made.push(b.id))
}

// ---- double-click on an existing block must NOT create one ----
{
  const beforeIds = new Set((await blocksOn(today)).map((b) => b.id))
  const box = await boxOf('ui-check walk')
  await page.mouse.dblclick(box.x + box.width / 2, box.y + 18)
  await page.waitForTimeout(400)
  const created = (await blocksOn(today)).filter((b) => !beforeIds.has(b.id))
  check('double-click on a block adds nothing', created.length === 0, `${created.length} new`)
  created.forEach((b) => made.push(b.id)) // never leave a stray behind
}

// ---- clicking a block opens the editor on that block ----
{
  const box = await boxOf('ui-check walk')
  await page.mouse.click(box.x + box.width / 2, box.y + 18)
  await page.waitForTimeout(250)
  check('clicking a block opens the editor', (await page.locator('.editor').count()) === 1)
  check('the editor shows that title', (await page.locator('.editor .title-input').inputValue()) === 'ui-check walk')
}

// ---- deleting from the editor ----
{
  await page.locator('.editor button.danger').click()
  await page.waitForTimeout(300)
  check('delete removes the block', !(await find(walk.id)))
  if (made.includes(walk.id)) made.splice(made.indexOf(walk.id), 1)
}

// ---- a day with nothing on it draws nothing ----
{
  await page.fill('.day-head input[type="date"]', EMPTY_DAY)
  await page.waitForTimeout(400)
  check('an empty day draws no blocks', (await page.locator('.content .block').count()) === 0)
  await page.fill('.day-head input[type="date"]', today)
  await page.waitForTimeout(400)
}

// ---- clean up this run's seeds, then re-check the render against the API ----
{
  for (const id of [...made]) await req(`/blocks/${id}`, { method: 'DELETE' })
  made.length = 0
  await page.reload({ waitUntil: 'networkidle' })
  const apiBlocks = (await blocksOn(today)).length
  const apiInbox = (await inboxNow()).length
  check(
    'after cleanup the timeline matches the API',
    (await page.locator('.content .block').count()) === apiBlocks,
    `${apiBlocks} in db`,
  )
  check(
    'after cleanup the inbox matches the API',
    (await page.locator('.inbox .chip').count()) === apiInbox,
  )
  check(
    'the inbox empty state appears exactly when the inbox is empty',
    ((await page.locator('.inbox .empty').count()) === 1) === (apiInbox === 0),
  )
}

check('no uncaught page errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))

await browser.close()

// never leave seeds behind, even on a failing run
for (const id of made) await req(`/blocks/${id}`, { method: 'DELETE' }).catch(() => {})

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
