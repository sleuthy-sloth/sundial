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
const pm = await spawn({ title: 'ui-check pm', day: today, start_min: 14 * 60, duration_min: 30, color: 'amber' })
const eve = await spawn({ title: 'ui-check eve', day: today, start_min: 19 * 60, duration_min: 30, color: 'indigo' })
const loose = await spawn({ title: 'ui-check inbox item', duration_min: 30 })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const consoleErrors = []
page.on('pageerror', (e) => consoleErrors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

await page.goto(BASE, { waitUntil: 'networkidle' })

// ---- the to-do list is home ----
{
  check('it opens on the to-do list, not the timeline', (await page.locator('.agenda').count()) === 1)
  check('with one capture field', (await page.locator('.capture-card input').count()) === 1)
  check('and the four parts of the day', (await page.locator('.section-pill').count()) === 4)

  const inSection = (section, text) =>
    page.locator(`${section} .card`).filter({ hasText: text }).count()

  check('a 9am task sits under Morning', (await inSection('.section-morning', 'ui-check walk')) === 1)
  check('a 2pm task sits under Afternoon', (await inSection('.section-afternoon', 'ui-check pm')) === 1)
  check('a 7pm task sits under Evening', (await inSection('.section-evening', 'ui-check eve')) === 1)
  check('unscheduled work waits under Anytime', (await inSection('.section-anytime', 'ui-check inbox item')) === 1)

  const counts = await page.locator('.section-pill .count').allInnerTexts()
  check('each section counts what it holds', counts.join(' ') === '(1) (2) (1) (1)', counts.join(' '))

  // the checkbox on a card completes the task
  const card = page.locator('.section-morning .card').filter({ hasText: 'ui-check walk' }).first()
  await card.locator('.tick').click()
  await page.waitForTimeout(300)
  check('the card checkbox marks it done', (await find(walk.id)).done === true)
  check('and the card shows it', (await page.locator('.card.done').count()) >= 1)
  await page.locator('.card.done .tick').first().click()
  await page.waitForTimeout(300)
  check('and un-marks it', (await find(walk.id)).done === false)

  // capture from the list
  await page.locator('.capture-card input').fill('ui-check captured')
  await page.locator('.capture-card input').press('Enter')
  await page.waitForTimeout(400)
  const captured = (await inboxNow()).find((b) => b.title === 'ui-check captured')
  check('typing in the capture field adds to Anytime', Boolean(captured))
  check('and it appears on the page', (await inSection('.section-anytime', 'ui-check captured')) === 1)
  if (captured) made.push(captured.id)
}

// ---- switching to the timeline ----
{
  await page.locator('.tabbar .tab').nth(1).click()
  await page.waitForSelector('.content .block')
  check('the tab bar switches to the timeline', (await page.locator('.content').count()) === 1)
  check('and shows which view you are in', (await page.locator('.tabbar .tab.on').count()) === 1)
}

// ---- what the timeline rendered ----
check('24 hour labels drawn', (await page.locator('.hour-label').count()) === 24)
check('the now line is on today', (await page.locator('.now').count()) === 1)
check(
  'the day heading is the weekday, in the serif',
  /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$/.test(
    (await page.locator('.day-title').innerText()).trim(),
  ),
  await page.locator('.day-title').innerText(),
)
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
  // Aim at a spot that is genuinely empty and clear of the tab bar, rather than
  // trusting a fixed offset to land somewhere sensible.
  const spot = await page.evaluate(() => {
    const content = document.querySelector('.content')
    const r = content.getBoundingClientRect()
    const x = r.left + r.width / 2
    const top = Math.max(r.top + 8, 170)
    const bottom = Math.min(r.bottom - 8, 780)
    for (let y = Math.round((top + bottom) / 2); y < bottom; y += 16) {
      const el = document.elementFromPoint(x, y)
      if (el && el.classList.contains('content')) return { y, offset: y - r.top }
    }
    return null
  })
  check('found an empty stretch of timeline to click', spot !== null)
  if (spot) {
    const expected = snapMin((spot.offset / 56) * 60)
    await page.mouse.dblclick(
      (await page.locator('.content').boundingBox()).x + (await page.locator('.content').boundingBox()).width / 2,
      spot.y,
    )
    await page.waitForTimeout(400)
    const created = (await blocksOn(today)).filter((b) => !beforeIds.has(b.id))
    check('double-click adds one block', created.length === 1, `${created.length} new`)
    check(
      'landing where you clicked',
      created[0]?.start_min === expected,
      `expected ${expected}, got ${created[0]?.start_min}`,
    )
    created.forEach((b) => made.push(b.id))
  }
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
  check('the week strip draws seven days', (await page.locator('.week-strip .day-pill').count()) === 7)

  const on = page.locator('.week-strip .day-pill.on')
  check('the day being viewed is on a pill', (await on.count()) === 1)
  const shown = (await on.locator('.pill-num').innerText()).trim()
  check('and it is the date being viewed', shown === String(Number(today.slice(8, 10))), shown)
  check('today is picked out in the accent', (await page.locator('.week-strip .day-pill.today').count()) === 1)

  await page.fill('.day-head input[type="date"]', EMPTY_DAY)
  await page.waitForTimeout(300)
  await page.locator('.today-pill').click()
  await page.waitForTimeout(300)
  check(
    'the Today pill comes back to today',
    (await page.locator('.day-head input[type="date"]').inputValue()) === today,
  )
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

// ---- what a slow, reordered or failed network must not do ----
// Every check above assumes the network answers immediately and in order. These hold
// requests open, answer them out of order, and fail them — which is what a phone on a
// bad connection does — and none of it may lose what was typed.
{
  const typing = await spawn({ title: 'ui-check typing', day: today, start_min: 21 * 60, duration_min: 30 })
  await page.reload({ waitUntil: 'networkidle' })
  const errorsBefore = consoleErrors.length

  const titleField = () => page.locator('.editor .title-input')
  const openEditorOn = async (title) => {
    const box = await boxOf(title)
    await page.mouse.click(box.x + box.width / 2, box.y + 18)
    await page.waitForSelector('.editor .title-input')
  }

  // 1. a write held open must not blank the field, and what was typed must still win
  {
    let held = null
    await page.route('**/api/blocks/*', (route) => {
      if (route.request().method() !== 'PATCH') return route.continue()
      if (!held) {
        held = route // leave this one unanswered until we say so
        return undefined
      }
      return route.continue()
    })

    await openEditorOn('ui-check typing')
    await titleField().fill('')
    await titleField().type('slow and deliberate', { delay: 15 })
    await page.waitForTimeout(700) // long enough for a debounce to fire; the write is held

    check(
      'a held-up write does not blank the field',
      (await titleField().inputValue()).length > 0,
      JSON.stringify(await titleField().inputValue()),
    )
    check(
      'and the field still shows what was typed',
      (await titleField().inputValue()) === 'slow and deliberate',
      await titleField().inputValue(),
    )

    const release = held
    held = null
    if (release) await release.continue()
    await page.waitForTimeout(800)
    check(
      'and the API ends up with that exact string',
      (await find(typing.id)).title === 'slow and deliberate',
      `stored ${JSON.stringify((await find(typing.id)).title)}`,
    )
    await page.unroute('**/api/blocks/*')
  }

  // 2. writes answered out of order: the last thing typed is what sticks
  {
    let first = true
    await page.route('**/api/blocks/*', async (route) => {
      if (route.request().method() !== 'PATCH') return route.continue()
      if (first) {
        first = false
        await new Promise((resolve) => setTimeout(resolve, 1200)) // the older write lands last
      }
      return route.continue()
    })

    await openEditorOn('slow and deliberate')
    await titleField().fill('')
    await titleField().type('a', { delay: 10 })
    await page.waitForTimeout(600) // the first write is sent, and is now held for 1.2s
    await titleField().type('bc', { delay: 10 })
    await page.waitForTimeout(2000)

    check(
      'an out-of-order write cannot put the old value back',
      (await find(typing.id)).title === 'abc',
      `stored ${JSON.stringify((await find(typing.id)).title)}`,
    )
    await page.unroute('**/api/blocks/*')
  }

  // 3. a failed write keeps the draft, says so, and can be tried again
  {
    let refuse = true
    await page.route('**/api/blocks/*', async (route) => {
      if (route.request().method() !== 'PATCH' || !refuse) return route.continue()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'the server said no' }),
      })
    })

    await openEditorOn('abc')
    await titleField().fill('ui-check after a failure')
    await page.waitForTimeout(700)

    check(
      'a failed save keeps what was typed',
      (await titleField().inputValue()) === 'ui-check after a failure',
      await titleField().inputValue(),
    )
    check(
      'and it says the save failed',
      (await page.locator('.editor-status[data-state="failed"]').count()) === 1,
    )
    check('with a way to try again', (await page.locator('.editor-status button').count()) === 1)

    refuse = false
    await page.locator('.editor-status button').click()
    await page.waitForTimeout(700)
    check(
      'and retrying saves it',
      (await find(typing.id)).title === 'ui-check after a failure',
      `stored ${JSON.stringify((await find(typing.id)).title)}`,
    )
    await page.unroute('**/api/blocks/*')
  }

  // 4. a slow answer for a day you have left must not paint over the day you are on
  {
    await page.route('**/api/day*', async (route) => {
      const asked = new URL(route.request().url()).searchParams.get('day')
      if (asked === today) await new Promise((resolve) => setTimeout(resolve, 1500))
      return route.continue()
    })

    await page.fill('.day-head input[type="date"]', EMPTY_DAY)
    await page.waitForTimeout(400)
    await page.locator('.today-pill').click() // starts a slow load for today
    await page.fill('.day-head input[type="date"]', EMPTY_DAY) // and go straight back
    await page.waitForTimeout(2400) // the slow answer for today lands in here

    check(
      'a late answer for another day does not paint over this one',
      (await page.locator('.content .block').count()) === 0,
      `${await page.locator('.content .block').count()} blocks drawn`,
    )
    check(
      'and the day on screen is still the one being viewed',
      (await page.locator('.day-head input[type="date"]').inputValue()) === EMPTY_DAY,
    )
    await page.unroute('**/api/day*')
    await page.fill('.day-head input[type="date"]', today)
    await page.waitForTimeout(500)
  }

  // 5. a capture that fails must not eat the text
  {
    await page.locator('.tabbar .tab').nth(0).click()
    await page.waitForTimeout(300)
    await page.route('**/api/blocks', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'the server said no' }),
      })
    })

    const capture = page.locator('.capture-card input')
    await capture.fill('ui-check kept draft')
    await capture.press('Enter')
    await page.waitForTimeout(700)

    check(
      'a capture that fails keeps what was typed',
      (await capture.inputValue()) === 'ui-check kept draft',
      await capture.inputValue(),
    )
    check(
      'and it did not reach the API',
      !(await inboxNow()).some((b) => b.title === 'ui-check kept draft'),
    )

    await page.unroute('**/api/blocks')
    await capture.press('Enter')
    await page.waitForTimeout(700)
    const kept = (await inboxNow()).find((b) => b.title === 'ui-check kept draft')
    check('and pressing Enter again saves it', Boolean(kept))
    if (kept) made.push(kept.id)

    await page.locator('.tabbar .tab').nth(1).click() // back to the timeline for the rest
    await page.waitForTimeout(300)
  }

  // This section fails requests on purpose, and the browser logs each one as a
  // resource error. Those are the check's own doing, so they are taken back out —
  // anything the page threw by itself still counts.
  consoleErrors.splice(errorsBefore, consoleErrors.length - errorsBefore)
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

  // back to the list: with nothing left, every part of the day offers a way in
  await page.locator('.tabbar .tab').nth(0).click()
  await page.waitForTimeout(300)
  check(
    'an empty list still offers every part of the day',
    (await page.locator('.card.empty').count()) === 4,
    `${await page.locator('.card.empty').count()} placeholders`,
  )
  check('and the capture field is still there', (await page.locator('.capture-card input').count()) === 1)
}

check('no uncaught page errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))

await browser.close()

// never leave seeds behind, even on a failing run
for (const id of made) await req(`/blocks/${id}`, { method: 'DELETE' }).catch(() => {})

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
