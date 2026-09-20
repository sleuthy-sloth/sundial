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

// ---- the week strip ----
{
  const week = (await req(`/week?start=${today}`)).days
  check('the week strip draws seven days', (await page.locator('.week-strip .day-pill').count()) === 7)
  check('every day carries a load bar', (await page.locator('.week-strip .pill-bar i').count()) === 7)

  const on = page.locator('.week-strip .day-pill.on')
  check('the day being viewed is marked', (await on.count()) === 1)
  const drawn = await on.locator('.pill-bar i').evaluate((el) => el.style.height)
  const minutes = week.find((d) => d.day === today).minutes
  const expected = `${Math.round(Math.min(minutes / 480, 1) * 100)}%`
  check('its bar reflects how booked the day is', drawn === expected, `${drawn} for ${minutes}m planned`)
}

// ---- theme ----
{
  const theme = () => page.evaluate(() => document.documentElement.dataset.theme)
  check('starts light', (await theme()) === 'light', await theme())

  await page.locator('.theme-toggle').click()
  await page.waitForTimeout(150)
  check('the toggle switches to dark', (await theme()) === 'dark')
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  check('and the page actually repaints', bg !== 'rgb(246, 247, 249)', bg)

  await page.reload({ waitUntil: 'networkidle' })
  check('the choice survives a reload', (await theme()) === 'dark')

  await page.locator('.theme-toggle').click()
  await page.waitForTimeout(150)
  check('and switches back', (await theme()) === 'light')
}

// ---- an icon on a block ----
{
  const icon_block = await spawn({ title: 'ui-check icon', day: today, start_min: 14 * 60, duration_min: 60 })
  await page.reload({ waitUntil: 'networkidle' })

  const box = await boxOf('ui-check icon')
  await page.mouse.click(box.x + box.width / 2, box.y + 18)
  await page.locator('.editor .icon-pick').nth(3).click() // nth(0) is the "no icon" dash
  await page.waitForTimeout(400)

  const stored = (await find(icon_block.id)).icon
  check('picking an icon stores it', stored.length > 0, `icon=${stored}`)
  check('and the block draws it', (await page.locator('.content .block .block-icon').count()) >= 1)
}

// ---- free time between blocks is visible, not implied ----
{
  await spawn({ title: 'ui-check gap a', day: today, start_min: 16 * 60, duration_min: 60 })
  await spawn({ title: 'ui-check gap b', day: today, start_min: 19 * 60, duration_min: 60 })
  await page.reload({ waitUntil: 'networkidle' })

  const gaps = page.locator('.content .gap')
  const heights = await gaps.evaluateAll((els) =>
    els.map((el) => Math.round(el.getBoundingClientRect().height)),
  )
  check('the two-hour hole is drawn as free time', heights.includes(2 * 56), `heights ${heights.join(', ')}`)
  const label = (await gaps.first().innerText()).trim()
  check('and it is labelled in plain words', /free$/.test(label), label)
}

// ---- an empty day says so in words ----
{
  await page.fill('.day-head input[type="date"]', EMPTY_DAY)
  await page.waitForTimeout(400)
  check('an empty day explains itself', (await page.locator('.timeline-empty').count()) === 1)
  await page.fill('.day-head input[type="date"]', today)
  await page.waitForTimeout(400)
}

// ---- the phone shape ----
{
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(300)
  const box = await boxOf('ui-check icon')
  await page.mouse.click(box.x + box.width / 2, box.y + 18)
  await page.waitForTimeout(300)

  const sheet = await page.locator('.editor').evaluate((el) => {
    const r = el.getBoundingClientRect()
    return { position: getComputedStyle(el).position, bottom: Math.round(r.bottom), vh: window.innerHeight }
  })
  check('the editor becomes a sheet on a phone', sheet.position === 'fixed', JSON.stringify(sheet))
  check('and sits at the bottom of the screen', Math.abs(sheet.bottom - sheet.vh) <= 2)
  check('with a grab handle', await page.locator('.sheet-grip').isVisible())

  const hit = await page.locator('.editor-actions button').first().evaluate((el) => el.getBoundingClientRect().height)
  check('its actions are thumb-sized', hit >= 44, `${Math.round(hit)}px`)

  await page.setViewportSize({ width: 1280, height: 900 })
}

// ---- reduced motion ----
{
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.waitForTimeout(100)
  const dur = await page.locator('.content .block').first().evaluate((el) => getComputedStyle(el).transitionDuration)
  check('reduced motion switches animation off', dur === '0s', dur)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
}

// ---- the PWA shell ----
{
  const res = await fetch(`${BASE}/manifest.webmanifest`)
  const manifest = await res.json()
  check('the manifest is served', res.ok && manifest.display === 'standalone', manifest.display)
  check('with icons to install from', (manifest.icons || []).length >= 2)

  const icon = await fetch(`${BASE}/apple-touch-icon.png`)
  check('the iOS home-screen icon exists', icon.ok && icon.headers.get('content-type') === 'image/png')

  const regs = await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)
  check('the service worker registered', regs >= 1, `${regs} registration(s)`)
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
