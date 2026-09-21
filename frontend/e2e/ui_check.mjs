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
const HOUR_PX = 72 // must match --hour-h / HOUR_PX in the app
const SNAP_MIN = 15
const today = new Date().toLocaleDateString('sv-SE')
const EMPTY_DAY = '2099-01-01' // a day nothing will ever be seeded on

let failures = 0
const check = (name, pass, detail = '') => {
  console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
  if (!pass) failures++
}

/** Wait for something to be true, rather than betting the runner is fast enough.
 *
 * Several checks here used to wait a fixed 300-400ms and then ask the API what happened.
 * That is a bet on the machine, and it lost in CI: the delete and empty-day checks failed
 * on a slow runner while passing everywhere else. Polling costs a fast machine nothing and
 * gives a slow one the time it needs, and the timeout still fails the check rather than
 * hanging. A request that fails mid-flight is simply not the answer yet. */
const until = async (fn, timeout = 6000, step = 50) => {
  const deadline = Date.now() + timeout
  let value
  for (;;) {
    try {
      value = await fn()
    } catch {
      value = undefined
    }
    if (value || Date.now() > deadline) return value
    await page.waitForTimeout(step)
  }
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
  check('and the four parts of the day', (await page.locator('.group-head').count()) === 4)

  const inSection = (section, text) =>
    page.locator(`${section} .row`).filter({ hasText: text }).count()

  check('a 9am task sits under Morning', (await inSection('.section-morning', 'ui-check walk')) === 1)
  check('a 2pm task sits under Afternoon', (await inSection('.section-afternoon', 'ui-check pm')) === 1)
  check('a 7pm task sits under Evening', (await inSection('.section-evening', 'ui-check eve')) === 1)
  check('unscheduled work waits under Anytime', (await inSection('.section-anytime', 'ui-check inbox item')) === 1)

  const counts = await page.locator('.group-head .count').allInnerTexts()
  check('each section counts what it holds', counts.join(' ') === '1 2 1 1', counts.join(' '))

  // The square on a row finishes the task. It fills at once, then the row leaves the list and
  // lands in the section's finished group — so the check has to follow it there.
  const row = page.locator('.section-morning .row').filter({ hasText: 'ui-check walk' }).first()
  await row.locator('.notch').click()
  check('the box marks it done', Boolean(await until(async () => (await find(walk.id))?.done === true)))
  check(
    'the row leaves the list for the finished group',
    Boolean(await until(async () => (await page.locator('.done-group .row.done').count()) >= 1)),
  )
  check(
    'and the section count drops it',
    Boolean(await until(async () => (await page.locator('.section-morning .group-head .count').innerText()) === '1')),
  )
  check(
    'the finished group counts it',
    Boolean(await until(async () => (await page.locator('.done-group .done-line .count').first().innerText()) === '1')),
  )
  await page.locator('.done-group .row.done .notch').first().click()
  check('and un-marks it', Boolean(await until(async () => (await find(walk.id))?.done === false)))

  // capture from the list
  await page.locator('.capture-card input').fill('ui-check captured')
  await page.locator('.capture-card input').press('Enter')
  const captured = await until(async () => (await inboxNow()).find((b) => b.title === 'ui-check captured'))
  check('typing in the capture field adds to Anytime', Boolean(captured))
  check(
    'and it appears on the page',
    Boolean(await until(async () => (await inSection('.section-anytime', 'ui-check captured')) === 1)),
  )
  if (captured) made.push(captured.id)
}

// ---- switching to the timeline ----
{
  await page.locator('.view-switch button').nth(1).click()
  await page.waitForSelector('.content .block')
  check('the header switch opens the timeline', (await page.locator('.content').count()) === 1)
  check('and says which view you are in', (await page.locator('.view-switch button[aria-pressed="true"]').count()) === 1)
}

// ---- what the timeline rendered ----
check('an hour rule an hour, a label every other one', (await page.locator('.hour-label').count()) === 12)
check('the content is taller than the window it scrolls in', await page.evaluate(() => {
  const s = document.querySelector('.scroller')
  return s.scrollHeight > s.clientHeight + 100
}))
check('and opening the day leaves it at the hour you are in, not midnight', await page.evaluate(() => {
  const s = document.querySelector('.scroller')
  return s.scrollTop > 0
}))
check('the now line is on today', (await page.locator('.now').count()) === 1)
check(
  'the header names the day compactly',
  // "Sun 20 Sep" or "Sun 20 Sept": the month name comes from the locale, its length does not
  /^[A-Za-z]{3,4} \d{1,2} [A-Za-z]{3,4}$/.test((await page.locator('.day-name').innerText()).trim()),
  await page.locator('.day-name').innerText(),
)
check('and the big serif weekday is gone', (await page.locator('.day-title').count()) === 0)
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

  const after = await until(async () => {
    const b = await find(loose.id)
    return b?.day === today && b?.start_min != null ? b : undefined
  })
  check('inbox drag schedules the block', after?.day === today && after?.start_min != null, `day=${after?.day}`)
  check('it lands under the pointer', after?.start_min === expected, `expected ${expected}, got ${after?.start_min}`)
  check('and it left the inbox', Boolean(await until(async () => (await inboxNow()).every((b) => b.id !== loose.id))))
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
    const expected = snapMin((spot.offset / HOUR_PX) * 60)
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
  check('delete removes the block', Boolean(await until(async () => !(await find(walk.id)))))
  if (made.includes(walk.id)) made.splice(made.indexOf(walk.id), 1)
}

// ---- a day with nothing on it draws nothing ----
{
  await page.fill('.day-head input[type="date"]', EMPTY_DAY)
  const settled = await until(async () => (await page.locator('.timeline-empty').count()) === 1)
  check('an empty day draws no blocks', Boolean(settled) && (await page.locator('.content .block').count()) === 0)
  await page.fill('.day-head input[type="date"]', today)
  await page.waitForTimeout(400)
}

// ---- the week strip ----
{
  const dayName = () => page.locator('.day-name').innerText()
  const start = await dayName()
  check('the header reads the day like an instrument', /^[A-Za-z]{3,4} \d{1,2} [A-Za-z]{3,4}$/.test(start), start)

  await page.locator('.head-row .step').first().click() // back a day
  check('stepping back moves the day', (await dayName()) !== start, `${start} -> ${await dayName()}`)
  check('and offers a way back to today', (await page.locator('.today-pill').count()) === 1)
  await page.locator('.today-pill').click()
  check('which returns to the day it started on', (await dayName()) === start, await dayName())
  check(
    'and then there is nothing to come back from',
    (await page.locator('.today-pill').count()) === 0,
  )

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

  const stored = (await until(async () => (await find(icon_block.id))?.icon)) || ''
  check('picking an icon stores it', stored.length > 0, `icon=${stored}`)
  check('and the block draws it', Boolean(await until(async () => (await page.locator('.content .block .block-icon').count()) >= 1)))
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
  check('the two-hour hole is drawn as open time', heights.includes(2 * HOUR_PX), `heights ${heights.join(', ')}`)
  const label = (await gaps.first().innerText()).trim()
  check('and it is labelled in plain words', /open$/.test(label), label)
}

// ---- an empty day says so in words ----
{
  await page.fill('.day-head input[type="date"]', EMPTY_DAY)
  check('an empty day explains itself', Boolean(await until(async () => (await page.locator('.timeline-empty').count()) === 1)))
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
    // Once a held write is let go, the question is what the API eventually holds, not what
    // it holds 800ms later on a fast machine.
    await until(async () => (await find(typing.id)).title === 'slow and deliberate')
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
    await until(async () => (await find(typing.id)).title === 'ui-check after a failure')
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
    await page.locator('.view-switch button').nth(0).click()
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

    await page.locator('.view-switch button').nth(1).click() // back to the timeline for the rest
    await page.waitForTimeout(300)
  }

  // This section fails requests on purpose, and the browser logs each one as a
  // resource error. Those are the check's own doing, so they are taken back out —
  // anything the page threw by itself still counts.
  consoleErrors.splice(errorsBefore, consoleErrors.length - errorsBefore)
}

// ---- keyboard, a cancelled gesture, and the end of the day ----
{
  // 1. a block opens from the keyboard, and the editor can be left the same way
  {
    const block = page.locator('.content .block').filter({ hasText: 'ui-check icon' }).first()
    await block.scrollIntoViewIfNeeded()
    await block.press('Enter')
    await page.waitForSelector('.editor .title-input')
    check('Enter on a focused block opens the editor', (await page.locator('.editor').count()) === 1)
    check(
      'and focus moves into the panel, not into a text field',
      await page.evaluate(() => document.activeElement?.classList.contains('editor')),
    )

    await page.keyboard.press('Escape')
    await page.waitForTimeout(250)
    check('Escape leaves the editor', (await page.locator('.editor').count()) === 0)
  }

  // 2. a date given in the editor schedules on that date, not on today
  {
    const future = '2099-01-02'
    const item = await spawn({ title: 'ui-check future', duration_min: 30 })
    await page.reload({ waitUntil: 'networkidle' })

    await page.locator('.inbox .chip').filter({ hasText: 'ui-check future' }).first().click()
    await page.waitForSelector('.editor .title-input')
    await page.locator('.editor input[type="date"]').fill(future)

    const landed = await until(async () => (await blocksOn(future)).find((b) => b.id === item.id))
    check('a date in the editor schedules on that date', landed?.day === future, `day=${landed?.day}`)
    check('and it is no longer on today', !(await blocksOn(today)).some((b) => b.id === item.id))
    await page.reload({ waitUntil: 'networkidle' })
  }

  // 3. a gesture the browser takes back is not a drop
  {
    const subject = await spawn({
      title: 'ui-check cancel',
      day: today,
      start_min: 22 * 60,
      duration_min: 30,
    })
    await page.reload({ waitUntil: 'networkidle' })

    const box = await boxOf('ui-check cancel')
    const x = box.x + box.width / 2
    const y = box.y + 18
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x, y + 4)
    await page.mouse.move(x, y + 2 * HOUR_PX) // a real drag, with the block following
    await page.evaluate(() => {
      window.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true }))
    })
    await page.mouse.up()
    await page.waitForTimeout(400)

    const after = (await blocksOn(today)).find((b) => b.id === subject.id)
    check(
      'a cancelled gesture leaves the block where it was',
      after?.start_min === 22 * 60,
      `start_min=${after?.start_min}`,
    )
  }

  // 4. an item dropped past the end of the day takes the latest position that fits
  {
    const late = await spawn({ title: 'ui-check late', duration_min: 90 })
    await page.reload({ waitUntil: 'networkidle' })

    // The day scrolls inside its own column now, so put that back to the top before
    // reaching for the chip — the rail beside it does not scroll at all.
    await page.evaluate(() => {
      const s = document.querySelector('.scroller')
      if (s) s.scrollTop = 0
    })
    const chip = await page
      .locator('.inbox .chip')
      .filter({ hasText: 'ui-check late' })
      .first()
      .boundingBox()
    await page.mouse.move(chip.x + 30, chip.y + 12)
    await page.mouse.down()
    await page.mouse.move(chip.x + 70, chip.y + 30) // start the drag, clear the threshold

    // Now scroll the far end of the day into view while still holding the item, which
    // is the only way to reach it: the timeline is taller than the window here.
    const spot = await page.evaluate((hourPx) => {
      // this runs in the page, so the scale has to be handed in rather than closed over
      const s = document.querySelector('.scroller')
      s.scrollTop = s.scrollHeight // still holding the item: this is how you reach the end
      const wanted = ((23 * 60 + 45) / 60) * hourPx
      const rect = document.querySelector('.content').getBoundingClientRect()
      return { y: rect.top + wanted, x: rect.left + rect.width / 2 }
    }, HOUR_PX)
    check(
      'the end of the day can be reached',
      spot.y > 40 && spot.y < 900 - 10,
      `y=${Math.round(spot.y)}`,
    )

    await page.mouse.move(spot.x, spot.y)
    await page.waitForTimeout(150)

    const preview = await page.evaluate(() => {
      const ghost = document.querySelector('.block.ghost')
      if (!ghost) return null
      return { top: parseFloat(ghost.style.top), height: parseFloat(ghost.style.height) }
    })
    check('the drop draws a preview', preview !== null)
    check(
      'and the preview fits inside the day',
      preview ? ((preview.top + preview.height) / HOUR_PX) * 60 <= 1440.5 : false,
      preview
        ? `${Math.round(((preview.top + preview.height) / HOUR_PX) * 60)} minutes in`
        : 'no preview',
    )

    await page.mouse.up()
    await page.waitForTimeout(500)
    const stored = (await blocksOn(today)).find((b) => b.id === late.id)
    check('the late drop is kept', Boolean(stored), `day=${stored?.day}`)
    check(
      'at the position the preview showed',
      Boolean(stored && preview) && Math.abs((preview.top / HOUR_PX) * 60 - stored.start_min) < 1,
      `preview ${preview ? Math.round((preview.top / HOUR_PX) * 60) : '?'} vs stored ${stored?.start_min}`,
    )
    check(
      'and it does not run past midnight',
      Boolean(stored) && stored.start_min + stored.duration_min <= 1440,
      stored ? `${stored.start_min} + ${stored.duration_min}` : 'not kept',
    )
    await page.evaluate(() => {
      const s = document.querySelector('.scroller')
      if (s) s.scrollTop = 0
    })
  }

  // 5. a tap, on a device that taps
  {
    const touchy = await browser.newContext({ hasTouch: true, viewport: { width: 390, height: 844 } })
    const touchPage = await touchy.newPage()
    try {
      await touchPage.goto(BASE, { waitUntil: 'networkidle' })
      await touchPage.locator('.view-switch button').nth(1).click()
      await touchPage.waitForSelector('.content .block')
      const target = touchPage.locator('.content .block').first()
      await target.scrollIntoViewIfNeeded()
      const box = await target.boundingBox()
      await touchPage.touchscreen.tap(box.x + box.width / 2, box.y + 18)
      await touchPage.waitForTimeout(400)
      check('a touch tap opens the editor', (await touchPage.locator('.editor').count()) === 1)
    } finally {
      await touchy.close()
    }
  }

  // 6. bigger text is bigger, and the layout holds
  {
    const size = () =>
      page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('.hour-label')).fontSize))
    const before = await size()

    // Exactly what a reader asking for bigger text does: raise the browser's base size.
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '32px'
    })
    await page.waitForTimeout(250)
    const after = await size()

    check('bigger text actually makes the type bigger', after > before * 1.5, `${before} -> ${after}`)
    const spill = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    check('and the page does not run off the side', spill <= 2, `${spill}px too wide`)

    await page.evaluate(() => {
      document.documentElement.style.fontSize = ''
    })
    await page.waitForTimeout(150)
  }
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

  // An upgrade only reaches the phone if the server says what may be kept. Both halves
  // are needed: the shell and the worker script must be revalidated, and the hashed
  // assets may be kept forever, because their names change when their contents do.
  const shell = await page.evaluate(async () => {
    const nav = await fetch('/', { cache: 'no-store' })
    return { cacheControl: nav.headers.get('cache-control'), status: nav.status }
  })
  check('the shell is not left for the browser to guess about', shell.cacheControl === 'no-cache', String(shell.cacheControl))

  const worker = await page.evaluate(async () => (await fetch('/sw.js')).headers.get('cache-control'))
  check('and neither is the service worker script', worker === 'no-cache', String(worker))

  const asset = await page.evaluate(async () => {
    const html = await (await fetch('/', { cache: 'no-store' })).text()
    const src = html.match(/\/assets\/[A-Za-z0-9._-]+\.js/)?.[0]
    if (!src) return null
    const response = await fetch(src)
    return { src, cacheControl: response.headers.get('cache-control') }
  })
  check(
    'while a hashed asset may be kept for good',
    Boolean(asset && (asset.cacheControl || '').includes('immutable')),
    asset ? `${asset.src}: ${asset.cacheControl}` : 'no script tag in the shell',
  )

  // The worker has to be the thing answering, or the offline shell is decoration.
  let controlling = await page.evaluate(() => Boolean(navigator.serviceWorker.controller))
  if (!controlling) {
    await page.reload({ waitUntil: 'networkidle' })
    controlling = await page.evaluate(() => Boolean(navigator.serviceWorker.controller))
  }
  check('and the worker is the one serving the page', controlling)
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
  await page.locator('.view-switch button').nth(0).click()
  await page.waitForTimeout(300)
  check(
    'an empty list still offers every part of the day',
    (await page.locator('.row.empty').count()) === 4,
    `${await page.locator('.row.empty').count()} placeholders`,
  )
  check('and the capture field is still there', (await page.locator('.capture-card input').count()) === 1)
}

// ---- the artwork ---------------------------------------------------------------------------
// Three states get a picture, in two themes each, and the words stay primary. Everything here
// is measured against the running app: the file that is actually showing, its real pixel size,
// and what the accessibility tree actually contains.
{
  const themeNow = () => page.evaluate(() => document.documentElement.dataset.theme)
  const wantTheme = async (want) => {
    if ((await themeNow()) !== want) {
      await page.locator('.theme-toggle').click()
      await page.waitForTimeout(200)
    }
  }
  // "empty-inbox-light-B5h3xgiZ.webp" -> "empty-inbox-light": the build hash is not the point
  const stem = (url) => {
    const file = (url || '').split('/').pop().replace(/\.webp$/, '')
    const parts = file.split('-')
    return parts.length > 3 ? parts.slice(0, -1).join('-') : file
  }
  /** The picture a state is actually showing, and the one it is holding in reserve. */
  const artOf = async (sel) =>
    page.evaluate((s) => {
      const wrap = document.querySelector(s)
      if (!wrap) return null
      const imgs = [...wrap.querySelectorAll('img')]
      const shown = imgs.find((i) => getComputedStyle(i).display !== 'none')
      const other = imgs.find((i) => i !== shown)
      const box = wrap.getBoundingClientRect()
      const cs = shown ? getComputedStyle(shown) : null
      return {
        ariaHidden: wrap.getAttribute('aria-hidden'),
        alt: shown ? shown.getAttribute('alt') : null,
        src: shown ? shown.currentSrc || shown.src : null,
        natural: shown && shown.naturalWidth ? `${shown.naturalWidth}x${shown.naturalHeight}` : null,
        otherSrc: other ? other.currentSrc || other.src : null,
        otherDisplay: other ? getComputedStyle(other).display : null,
        width: box.width,
        height: box.height,
        motion: cs ? `${cs.transitionDuration} ${cs.animationName}` : null,
      }
    }, sel)

  const RESERVED = '800x537'
  // The reserved box is only right if ONE file is drawing. If the hidden one is not actually
  // hidden the two stack and the wrapper is twice as tall — which is exactly what happened.
  const oneImageWide = (box) =>
    Boolean(box) && box.width > 0 && Math.abs(box.height / box.width - 537 / 800) < 0.03

  // 1. the empty inbox (the suite is sitting on one: nothing left, no blocks at all)
  {
    await wantTheme('light')
    await page.locator('.view-switch button').nth(1).click() // the rail is the timeline's
    await until(async () => (await page.locator('.inbox').count()) === 1)
    check('the inbox really is empty before we look at it', (await inboxNow()).length === 0)
    const box = await artOf('.inbox-empty .art')
    check('the empty inbox shows the tray', Boolean(box) && box.width > 0, box ? `${Math.round(box.width)}px wide` : 'no .inbox-empty')
    check('and it is the light file', Boolean(box) && stem(box.src) === 'empty-inbox-light', stem(box?.src))
    check('at the size we reserved for it', Boolean(box) && box.natural === RESERVED, String(box?.natural))
    check('and only one of the two files is drawn', oneImageWide(box), box ? `${Math.round(box.width)}x${Math.round(box.height)}` : 'absent')
    check(
      'the sentence is still there to explain it',
      ((await page.locator('.inbox-empty').innerText()) || '').includes('Nothing waiting'),
    )
    check(
      'and the picture is decoration, not content',
      Boolean(box) && box.ariaHidden === 'true' && box.alt === '',
      `aria-hidden=${box?.ariaHidden} alt=${JSON.stringify(box?.alt)}`,
    )
    check(
      'the dark file waits, and is not the one showing',
      Boolean(box) && box.otherSrc !== box.src && box.otherDisplay === 'none',
      `other display=${box?.otherDisplay}`,
    )
    check('nothing animates it', Boolean(box) && box.motion === '0s none', String(box?.motion))

    await wantTheme('dark')
    const dark = await artOf('.inbox-empty .art')
    check('the dark theme gets the dark tray', Boolean(dark) && stem(dark.src) === 'empty-inbox-dark', stem(dark?.src))
    check(
      'and the light one is hidden rather than merely beneath',
      Boolean(dark) && dark.otherDisplay === 'none',
      `light display=${dark?.otherDisplay}`,
    )
    await wantTheme('light')
  }

  // 2. the empty timeline, on a day nothing will ever be seeded on
  {
    await page.locator('.view-switch button').nth(1).click()
    await page.fill('.day-head input[type="date"]', EMPTY_DAY)
    await until(async () => (await page.locator('.state-timeline .art').count()) === 1)

    const light = await artOf('.state-timeline .art')
    check('an empty timeline puts the dial on the rail', Boolean(light) && light.width > 0, light ? `${Math.round(light.width)}px wide` : 'absent')
    check('and it is the light file', Boolean(light) && stem(light.src) === 'empty-timeline-light', stem(light?.src))
    check('at the size we reserved for it', Boolean(light) && light.natural === RESERVED, String(light?.natural))
    check('and only one of the two files is drawn', oneImageWide(light), light ? `${Math.round(light.width)}x${Math.round(light.height)}` : 'absent')
    check(
      'with the instruction still doing the explaining',
      ((await page.locator('.timeline-empty').innerText()) || '').includes('Nothing planned yet'),
    )
    check(
      'and it is kept off the accessibility tree',
      Boolean(light) && light.ariaHidden === 'true' && light.alt === '',
    )

    // the screen-reader view of the same state: the sentence is there, the picture is not
    const spoken = await page.locator('.content').ariaSnapshot()
    check('a screen reader is told the state', spoken.includes('Nothing planned yet'), spoken.split('\n')[0])
    check(
      'and never told about the dial',
      !/dial|sundial|illustration|image/i.test(spoken),
      spoken.replace(/\n/g, ' ').slice(0, 60),
    )

    await wantTheme('dark')
    const dark = await artOf('.state-timeline .art')
    check('the dial has a dark twin', Boolean(dark) && stem(dark.src) === 'empty-timeline-dark', stem(dark?.src))
    await wantTheme('light')
    await page.fill('.day-head input[type="date"]', today)
    await page.locator('.view-switch button').nth(0).click()
    await page.waitForTimeout(400)
  }

  // 3. the all-clear, which is the one picture with a condition attached
  {
    check('an empty day does not claim to be finished', (await page.locator('.state-complete').count()) === 0)

    const finisher = await spawn({ title: 'ui-check finished the day', duration_min: 30, day: today, start_min: 600 })
    await page.reload({ waitUntil: 'networkidle' }) // the app has to see the new block
    // finish it the way a person does, so this tests the app's own completion path
    await page.locator('.agenda .row .notch').first().click()
    const shown = await until(async () => (await page.locator('.state-complete .art').count()) === 1)
    check('a finished day says so', Boolean(shown))

    const all = await artOf('.state-complete .art')
    check('with the low sun, light file', Boolean(all) && stem(all.src) === 'day-complete-light', stem(all?.src))
    check('at the size we reserved for it', Boolean(all) && all.natural === RESERVED, String(all?.natural))
    check('and only one of the two files is drawn', oneImageWide(all), all ? `${Math.round(all.width)}x${Math.round(all.height)}` : 'absent')
    check('once, not once per section', (await page.locator('.state-complete').count()) === 1)
    check(
      'and no section wears the artwork',
      (await page.locator('.section-body .art').count()) === 0,
      `${await page.locator('.section-body .art').count()} in sections`,
    )

    await wantTheme('dark')
    const darkAll = await artOf('.state-complete .art')
    check('and a dark twin for it', Boolean(darkAll) && stem(darkAll.src) === 'day-complete-dark', stem(darkAll?.src))
    await wantTheme('light')

    // put it back the way a person does — one tap on the row in the finished group — because
    // an API call the app never hears about would leave the panel on screen and the check
    // would be measuring the app's memory rather than its behaviour
    await page.locator('.done-group .row .notch').first().click()
    check(
      'and it stops claiming when something is left',
      Boolean(await until(async () => (await page.locator('.state-complete').count()) === 0)),
    )
    await req(`/blocks/${finisher.id}`, { method: 'DELETE' }).catch(() => {})
    if (made.includes(finisher.id)) made.splice(made.indexOf(finisher.id), 1)
  }

  // 4. what the build actually serves: the hashed art, the card, the icons
  {
    // Enumerated from the build rather than from whatever is on screen: a state that is not
    // being visited right now still has to have shipped its files, and an empty list would make
    // these two checks pass without testing anything, which is the failure mode that bit the
    // first version of this block.
    const results = await page.evaluate(async () => {
      const html = await (await fetch('/')).text()
      const bundle = html.match(/\/assets\/index-[A-Za-z0-9._-]+\.js/)
      const src = bundle ? await (await fetch(bundle[0])).text() : ''
      const urls = [...new Set(src.match(/\/assets\/[A-Za-z0-9._-]+\.webp/g) || [])]
      const out = []
      for (const u of urls) {
        const r = await fetch(u)
        out.push({ u, status: r.status, type: r.headers.get('content-type'), cc: r.headers.get('cache-control') })
      }
      return out
    })
    check(
      'all six empty-state files shipped, and every one is served',
      results.length === 6 && results.every((r) => r.status === 200 && (r.type || '').includes('webp')),
      results.map((r) => `${r.u.split('/').pop()}:${r.status}`).join(' '),
    )
    check(
      'and each is content-hashed and kept for good',
      results.length === 6 && results.every((r) => /-[A-Za-z0-9_-]{8}\.webp$/.test(r.u) && (r.cc || '').includes('immutable')),
      results[0] ? results[0].cc : 'nothing to check',
    )

    // the card, at the address the page advertises for it
    const card = await page.evaluate(async () => {
      const tag = document.querySelector('meta[property="og:image"]')
      const w = document.querySelector('meta[property="og:image:width"]')
      const h = document.querySelector('meta[property="og:image:height"]')
      if (!tag) return null
      const url = new URL(tag.content, location.origin).href
      const res = await fetch(url)
      const type = res.headers.get('content-type')
      // decode it: the advertised size should be the file's real size, not a hopeful label
      let real = null
      try {
        real = await createImageBitmap(await res.blob())
      } catch {
        real = null
      }
      return {
        url,
        status: res.status,
        type,
        declared: `${w?.content}x${h?.content}`,
        real: real ? `${real.width}x${real.height}` : null,
        card: document.querySelector('meta[name="twitter:card"]')?.content,
      }
    })
    check('the social card resolves at the address we advertise', card?.status === 200 && (card?.type || '').includes('jpeg'), `${card?.url} -> ${card?.status} ${card?.type}`)
    check('and it really is 1200x630', card?.real === '1200x630', `declared ${card?.declared}, decoded ${card?.real}`)
    check('a large card, so the picture is the preview', card?.card === 'summary_large_image', String(card?.card))

    const icons = await page.evaluate(async () => {
      const paths = ['/favicon.svg', '/favicon-32.png', '/apple-touch-icon.png', '/icon-maskable-512.png']
      const out = {}
      for (const p of paths) out[p] = (await fetch(p)).status
      const manifest = await (await fetch('/manifest.webmanifest')).json()
      return { out, maskable: (manifest.icons || []).filter((i) => i.purpose === 'maskable').map((i) => i.src) }
    })
    check(
      'the favicon and the home-screen icons are all served',
      Object.values(icons.out).every((s) => s === 200),
      Object.entries(icons.out).map(([p, s]) => `${p.split('/').pop()}:${s}`).join(' '),
    )
    check(
      'and the maskable ones are the padded files, not the plain icons',
      icons.maskable.length === 2 && icons.maskable.every((s) => s.includes('maskable')),
      icons.maskable.join(' '),
    )

    const shell = await page.evaluate(async () => (await fetch('/')).text())
    check(
      'no build placeholder is left in the shell',
      !shell.includes('%VITE_'),
      shell.includes('%VITE_') ? 'a %VITE_% was not replaced' : 'clean',
    )
  }

  // 5. a slow connection: the box is the right shape before the picture arrives.
  //    A fresh context, because the pictures are already in this page's cache and a cached
  //    response never reaches the route — the first run of this check passed without ever
  //    delaying anything, which is the sort of false pass worth waiting for.
  {
    // service workers are blocked: the app's worker answers asset requests from its own cache,
    // and Playwright cannot route a request the worker makes, so the delay never applied
    const slow = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
    const page = await slow.newPage()
    try {
    await page.route('**/*.webp', async (route) => {
      await new Promise((r) => setTimeout(r, 1500))
      await route.continue()
    })
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.view-switch')
    // choose the day first: the artwork is the same file for every empty day, so if the
    // timeline draws once before this it is cached, the route never sees a request, and the
    // check passes without ever testing a slow connection
    await page.fill('.day-head input[type="date"]', EMPTY_DAY)
    await page.locator('.view-switch button').nth(1).click()
    await page.waitForSelector('.state-timeline .art')

    const pending = await page.evaluate(() => {
      const img = document.querySelector('.state-timeline .art img:not([style*="none"])')
      const wrap = document.querySelector('.state-timeline .art')
      const box = wrap.getBoundingClientRect()
      const loaded = [...wrap.querySelectorAll('img')].some((i) => i.complete && i.naturalWidth > 0)
      return { width: box.width, height: box.height, loaded }
    })
    check('while the art is still in flight it has not loaded', pending.loaded === false, JSON.stringify(pending.loaded))
    check(
      'and its box is already the right shape',
      pending.width > 0 && Math.abs(pending.height / pending.width - 537 / 800) < 0.02,
      `${Math.round(pending.width)}x${Math.round(pending.height)}`,
    )

    await page.waitForTimeout(2500)
    const arrived = await page.evaluate(() => {
      const box = document.querySelector('.state-timeline .art').getBoundingClientRect()
      return { width: box.width, height: box.height }
    })
    check(
      'so nothing moves when it lands',
      Math.abs(arrived.height - pending.height) < 1 && Math.abs(arrived.width - pending.width) < 1,
      `${Math.round(pending.width)}x${Math.round(pending.height)} -> ${Math.round(arrived.width)}x${Math.round(arrived.height)}`,
    )
    } finally {
      await slow.close() // its own context, so the rest of the run keeps its cache
    }
  }
}


check('no uncaught page errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))

await browser.close()

// never leave seeds behind, even on a failing run
for (const id of made) await req(`/blocks/${id}`, { method: 'DELETE' }).catch(() => {})

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
