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

/** The text of an element that might not be there. A missing state should fail its own check,
 *  not throw and take every check after it out of the run — which is exactly what an unguarded
 *  innerText() on an absent element did. */
const textOf = async (sel) =>
  (await page.locator(sel).count()) > 0 ? (await page.locator(sel).first().innerText()) : ''

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
  await page.locator('.tabs button[data-tab="day"]').click()
  await page.waitForSelector('.content .block')
  check('the bar opens the timeline', (await page.locator('.content').count()) === 1)
  check('and says which destination you are in', (await page.locator('.tabs button[aria-current="page"]').count()) === 1)
}

// ---- the shell: three destinations at the foot of the app --------------------
// The navigation, replaced wholesale. A switch in the header plus a rail beside the day is what
// put the app's own plumbing — credentials, sync, theme — in the same column as your plan, so
// connecting a calendar sat under your inbox as though it were plan material. These checks pin
// what took its place, and pin that the old controls are actually gone, which is the part a
// stylesheet can lie about.
{
  const shell = async () => ({
    labels: (await page.locator('.tabs button').allTextContents()).map((t) => t.trim()).join('/'),
    current: await page.locator('.tabs button[aria-current="page"]').count(),
    switches: await page.locator('.view-switch').count(),
    rail: await page.locator('.side').isVisible().catch(() => false),
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.tabs')

  let s = await shell()
  check('a phone gets three destinations, named', s.labels === 'Today/Day/You', s.labels)
  check('exactly one of them says you are there', s.current === 1)
  check('the header switch is gone, not just restyled', s.switches === 0)
  check('and the rail no longer spends a quarter of a phone screen above the plan', !s.rail)

  const bar = await page.locator('.tabs').boundingBox()
  check(
    'the bar is at the foot of the window, where a thumb is',
    bar.y + bar.height <= 845 && bar.y > 700,
    `y ${Math.round(bar.y)}..${Math.round(bar.y + bar.height)} of 844`,
  )

  const behind = []
  for (const key of ['today', 'day', 'you']) {
    const b = await page.locator(`.tabs button[data-tab="${key}"]`).boundingBox()
    const top = await page.evaluate(
      ([x, y]) => {
        const el = document.elementFromPoint(x, y)
        return el?.closest('.tabs button')?.dataset.tab ?? (el ? el.tagName : 'none')
      },
      [b.x + b.width / 2, b.y + b.height / 2],
    )
    behind.push(`${key}:${top === key ? 'ok' : 'BEHIND ' + top}`)
  }
  check('every destination is the thing on top at its own centre', behind.every((b) => b.endsWith('ok')), behind.join(' '))

  // Each one shows what it says it does, and the other one leaves the screen: a destination that
  // merely adds its panel below the previous one is not navigation.
  const goes = []
  for (const [key, here, away] of [['today', null, '.content'], ['day', '.content', null], ['you', '.cal', '.content']]) {
    await page.locator(`.tabs button[data-tab="${key}"]`).click()
    await page.waitForTimeout(350)
    const shown = await page.locator(`.tabs button[data-tab="${key}"][aria-current="page"]`).count()
    const got = here ? await page.locator(here).count() : 1
    const left = away ? await page.locator(away).count() : 0
    goes.push(`${key}:${shown === 1 && got > 0 && left === 0 ? 'ok' : `shown=${shown} here=${got} gone=${left}`}`)
  }
  check('today is the plan, day is the clock, you is the settings', goes.every((g) => g.endsWith('ok')), goes.join(' '))

  await page.locator('.tabs button[data-tab="you"]').click()
  await page.waitForTimeout(350)
  check(
    'connecting is something you reach from the profile tab, not from beside your day',
    (await page.locator('.cal-connect-open').count()) === 1,
  )
  await page.locator('.cal-connect-open').click()
  const opened = await page.locator('.cal-input').count()
  await page.locator('.cal-cancel').click()
  check(
    'and its form opens and closes where it stands',
    opened === 2 && (await page.locator('.cal-input').count()) === 0,
    `opened ${opened}`,
  )
  // The theme is toggled in the header and stated here as a setting. Since the switches
  // arrived it states it by position, the same control the notifications row below it uses —
  // and every way a copy-pasted switch fails is asserted, because a switch that cannot be
  // reached or that opts out of the ring is worse than the button it replaced.
  const themeSwitch = page.locator('.theme-switch')
  const themeInput = themeSwitch.locator('input')
  check(
    'the theme is stated as a setting here too, and as a switch',
    (await themeSwitch.count()) === 1 && (await themeInput.getAttribute('role')) === 'switch',
    `${await themeSwitch.count()} switch in the theme row`,
  )
  check(
    'the theme switch is reachable by keyboard, not only by click',
    await themeInput.evaluate((el) => el.tabIndex >= 0),
  )
  check(
    'and it shows the theme that is actually in force',
    (await themeInput.isChecked()) ===
      ((await page.evaluate(() => document.documentElement.dataset.theme)) === 'dark'),
  )

  // A programmatic focus does not match :focus-visible, so press Tab first to put the browser
  // into keyboard modality. Without that this would pass while asserting nothing.
  await page.keyboard.press('Tab')
  await themeInput.focus()
  const ring = await themeSwitch.locator('.switch-track').evaluate((el) => {
    const s = getComputedStyle(el)
    return { w: s.outlineWidth, st: s.outlineStyle, off: s.outlineOffset }
  })
  check(
    'and it draws the same focus ring every other control gets',
    ring.w === '2px' && ring.st === 'solid' && ring.off === '2px',
    `outline ${ring.w} ${ring.st}, offset ${ring.off}`,
  )

  // Wide: the bar stays the navigation, and the rail returns beside the clock — where an
  // unscheduled task has a timeline to be dragged onto.
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.tabs')
  await page.locator('.tabs button[data-tab="day"]').click()
  await page.waitForTimeout(400)
  s = await shell()
  check('the bar is the navigation at 1280 as well', s.current === 1 && s.switches === 0, `${s.current} current, ${s.switches} switches`)
  check('and there the rail comes back, because a drag needs somewhere to land', s.rail, `rail visible: ${s.rail}`)
  await page.waitForSelector('.content .block')
}

// ---- what the timeline rendered ----
check('an hour rule an hour, a label every other one', (await page.locator('.hour-label').count()) === 12)
check('the content is taller than the window it scrolls in', await page.evaluate(() => {
  const s = document.querySelector('.scroller')
  return s.scrollHeight > s.clientHeight + 100
}))
// "Opens at the hour you are in, not midnight" used to be asserted as `scrollTop > 0`, which is
// false for the first eighty minutes of every day: the app scrolls to half an hour ago minus
// 60px, so just after midnight the correct position IS the top. The check passed all evening and
// started failing when the clock crossed midnight — with nothing wrong in the app. Compute the
// position the app's own rule implies, in the browser's clock, and assert that: stronger than a
// sign test, and true at every hour.
{
  // HOUR_PX is a Node constant: page.evaluate runs in the browser, so it has to be handed in.
  //
  // The clamp is the half of this that cost a red run to find: a browser will not scroll past
  // the end, so late in the day "half an hour ago" sits further down than the content below it
  // allows and the app lands on the last screenful. Comparing against the unclamped number
  // passes all morning and fails at 15:19 UTC — a test measuring the hour, not the app.
  const { want, room } = await page.evaluate((hourPx) => {
    const now = new Date()
    const focusMin = now.getHours() * 60 + now.getMinutes() - 30
    const scroller = document.querySelector('.scroller')
    const roomLeft = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    return {
      room: roomLeft,
      want: Math.min(roomLeft, Math.max(0, (focusMin / 60) * hourPx - 60)),
    }
  }, HOUR_PX)
  const at = await until(async () => {
    const back = await page.evaluate(() => document.querySelector('.scroller')?.scrollTop ?? 0)
    return Math.abs(back - want) <= 4 ? back : null // 4px covers a minute boundary and rounding
  })
  check(
    'and opening the day lands half an hour before now, not at midnight',
    at !== null,
    `at ${await page.evaluate(() => Math.round(document.querySelector('.scroller')?.scrollTop ?? -1))}px, ` +
      `expected ${Math.round(want)}px with ${Math.round(room)}px of room`,
  )
}
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
  // Within a snap step rather than exactly on it: the app snaps to 15 minutes, so a pointer a
  // pixel either side of a boundary is a different number, and this check failed in CI twice for
  // that reason while passing everywhere else. One step still says the block landed where it was
  // dropped, rather than at the top of the day or in the wrong hour.
  const offBy = after?.start_min == null ? null : Math.abs(after.start_min - expected)
  check(
    'it lands under the pointer',
    offBy != null && offBy <= SNAP_MIN,
    `expected ${expected}, got ${after?.start_min}`,
  )
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
    // Measure the app's own scale rather than assuming the constant: a deployment can serve
    // a different one (text size, zoom), and at an exact half-step boundary that difference
    // decides which way the snap goes. This check has failed by one snap step for that
    // reason before.
    const pxPerHour = await page.evaluate(
      () =>
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--hour-h'),
        ) || 72,
    )
    const expected = snapMin((spot.offset / pxPerHour) * 60)
    await page.mouse.dblclick(
      (await page.locator('.content').boundingBox()).x + (await page.locator('.content').boundingBox()).width / 2,
      spot.y,
    )
    await until(async () => (await blocksOn(today)).filter((b) => !beforeIds.has(b.id)).length === 1)
    const created = (await blocksOn(today)).filter((b) => !beforeIds.has(b.id))
    check('double-click adds one block', created.length === 1, `${created.length} new`)
    // Within a snap step: the click is a pixel and the answer is a quarter hour, so a
    // half-pixel of rounding at a boundary is not a defect worth failing a build over. A
    // block landing a whole step away is.
    check(
      'landing where you clicked',
      Math.abs((created[0]?.start_min ?? -1e9) - expected) <= SNAP_MIN,
      `expected ${expected}, got ${created[0]?.start_min}`,
    )
    created.forEach((b) => made.push(b.id))
  }
}

// ---- double-click on an existing block must NOT create one ----
{
  // The app writes through a queue, so a block can still be in flight when the ids below are
  // taken — and it would then be counted as the one this check asserts was not created. The
  // header of this file says polling beats betting on the machine; this check still used a
  // fixed 400ms wait, which held until the run in front of it got longer. Wait for the API and
  // the DOM to agree instead.
  await until(async () => (await blocksOn(today)).length === (await page.locator('.content .block').count()))
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
  // Move the app to the empty day and confirm it actually moved. Filling a date and then asking
  // what the day holds are two different questions: on a loaded runner the change event can land
  // after the poll has already fixed on today, and the check then reports five blocks and no
  // empty state — which is exactly what it reported from CI while passing everywhere else. A
  // synthetic event that gets lost is a fact about the harness, not about the app, so set it
  // again if it did not take; a failure after that is about the app.
  const dateBox = '.day-head input[type="date"]'
  const moved = await until(async () => {
    if ((await page.locator('.timeline-empty').count()) === 1) return true
    // Set it again, and go on setting it while the app has not moved. Reading the field back is
    // not enough to know a change event landed: fs fill sets the input's value whether or not
    // React heard about it, so a lost event leaves a field that reads the empty day above a
    // timeline still drawing today — five blocks and no empty state, which is exactly what this
    // reported from CI while passing here. The empty state is the app's own evidence.
    await page.fill(dateBox, EMPTY_DAY)
    return (await page.locator('.timeline-empty').count()) === 1
  })
  check('the empty day is the day the app is actually showing', Boolean(moved),
    `empty state ${await page.locator('.timeline-empty').count()}, field ${await page.locator(dateBox).inputValue()}`)

  // And wait for the assertion itself rather than a proxy for it: this used to wait for the empty
  // state to appear and then read the block count one round later.
  const empty = await until(async () =>
    (await page.locator('.timeline-empty').count()) === 1 &&
    (await page.locator('.content .block').count()) === 0)
  check('an empty day draws no blocks', Boolean(empty),
    `empty state ${await page.locator('.timeline-empty').count()}, blocks ${await page.locator('.content .block').count()}`)
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
    await page.locator('.tabs button[data-tab="today"]').click()
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

    await page.locator('.tabs button[data-tab="day"]').click() // back to the timeline for the rest
    await page.waitForTimeout(300)
  }

  // This section fails requests on purpose, and the browser logs each one as a
  // resource error. Those are the check's own doing, so they are taken back out —
  // anything the page threw by itself still counts.
  consoleErrors.splice(errorsBefore, consoleErrors.length - errorsBefore)
}

// ---- the calendar inside the day ----
// The /api/events shape is pinned by the backend tests; what is unverified until here is the
// drawing, so the response is mocked. The day and the blocks are seeded inside this block rather
// than borrowed from earlier in the run: other checks move and delete blocks, and a section that
// assumed them would pass or fail depending on where in the file it sat.
{
  const DAY = EMPTY_DAY
  const pad = (n) => String(n).padStart(2, '0')
  const localISO = (h, m) => new Date(`${DAY}T${pad(h)}:${pad(m)}:00`).toISOString()
  const ev = (id, title, from, to, extra = {}) => ({
    id, title, calendar_ref: 'work', all_day: 0,
    start_utc: localISO(...from), end_utc: localISO(...to), ...extra,
  })

  await spawn({ title: 'ui-check deep', day: DAY, start_min: 600, duration_min: 120, color: 'violet' })
  await spawn({ title: 'ui-check pt', day: DAY, start_min: 420, duration_min: 60, color: 'emerald' })
  await spawn({ title: 'ui-check far', day: DAY, start_min: 840, duration_min: 30, color: 'amber' })

  const mocked = [
    ev('e1', 'ui-check review', [10, 15], [11, 0]),   // inside the 10:00 block
    ev('e2', 'ui-check call', [10, 30], [11, 0]),     // and overlapping e1: the half must be shared
    ev('e3', 'ui-check dental', [6, 45], [7, 15]),    // partial overlap with the 07:00 block
    ev('e4', 'ui-check dinner', [21, 0], [22, 0]),    // nothing planned: the half, whole
    ev('e5', 'ui-check allday', [0, 0], [0, 0], { all_day: 1 }),
    ev('e6', 'ui-check nothing', [12, 0], [12, 0]),
  ]
  await page.route('**/api/events*', (route) => route.fulfill({ json: { day: DAY, count: mocked.length, events: mocked } }))
  await page.fill('.day-head input[type="date"]', DAY)
  await until(async () => (await page.locator('.appt').count()) === 4)
  await page.waitForTimeout(200)

  const drawn = await page.locator('.appt').count()
  check('the day draws the appointments that have an hour', drawn === 4, `${drawn} drawn from six events`)
  check('an all-day event and a zero-length one are not rows on the clock',
    !(await page.locator('.appt').allInnerTexts()).some((t) => /allday|nothing/i.test(t)))

  const ink = await page.evaluate(() => ({
    appt: getComputedStyle(document.querySelector('.appt-title')).color,
    block: getComputedStyle(document.querySelector('.block-title')).color,
    weight: getComputedStyle(document.querySelector('.appt-title')).fontWeight,
  }))
  check('an appointment reads in the same ink as the plan', ink.appt === ink.block, `${ink.appt} vs ${ink.block}`)
  check('and at the same weight, not lightened to look "not mine"', ink.weight === '500', ink.weight)

  const titles = await page.evaluate(() => {
    const out = []
    document.querySelectorAll('.appt').forEach((a) => {
      const t = a.querySelector('.appt-title')
      t.scrollIntoView({ block: 'center' })
      const r = t.getBoundingClientRect()
      const hit = document.elementFromPoint(Math.round(r.left + Math.min(24, r.width / 2)), Math.round(r.top + r.height / 2))
      out.push({ text: t.textContent, clipped: t.scrollWidth > t.clientWidth + 1, onTop: !!hit && a.contains(hit) })
    })
    return out
  })
  check('every appointment title is the thing on top at its own centre',
    titles.every((t) => t.onTop), titles.filter((t) => !t.onTop).map((t) => t.text).join(', ') || 'all four')
  check('and none of them is truncated', titles.every((t) => !t.clipped),
    titles.filter((t) => t.clipped).map((t) => t.text).join(', ') || 'none')

  const clash = await page.evaluate(() => {
    // Two rectangles overlap only if they overlap in BOTH axes: comparing horizontal extents
    // alone calls two appointments hours apart "covering" each other, because they legitimately
    // share the same band of the column.
    const box = (el) => {
      const r = el.getBoundingClientRect()
      return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), w: Math.round(r.width) }
    }
    const colWidth = box(document.querySelector('.content')).w
    const byEvent = (id) => document.querySelector(`.appt[data-event="${id}"]`)
    const blocks = [...document.querySelectorAll('.block.clash')].map((el) => ({ ...box(el), text: el.textContent }))
    const appts = [...document.querySelectorAll('.appt.clash')].map((el) => ({ ...box(el), text: el.textContent }))
    const overlaps = (a, b) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b
    const cross = []
    for (const b of blocks) for (const a of appts) if (overlaps(a, b)) cross.push(`${b.text.slice(0, 12)} / ${a.text.slice(0, 12)}`)
    const alone = box(byEvent('e3'))
    const ones = [box(byEvent('e1')), box(byEvent('e2'))]
    return {
      blocks: blocks.length, appts: appts.length, cross, colWidth,
      aloneShare: alone.w / colWidth,
      contest: ones.map((o) => ({ w: o.w, l: o.l })),
      contestOverlap: overlaps(ones[0], ones[1]),
    }
  })
  check('the blocks that share an hour with the calendar give up half the column', clash.blocks === 2, `${clash.blocks} squeezed`)
  check('and the squeezed block and the appointment sit beside each other, not on top',
    clash.cross.length === 0, clash.cross.join(' ') || 'no overlap')
  check('an appointment with the free half to itself takes it',
    clash.aloneShare >= 0.4, `${Math.round(clash.aloneShare * 100)}% of the column`)
  check('and two contesting it still each hold a readable width',
    clash.contest.every((c) => c.w >= 120), `${clash.contest.map((c) => c.w).join('px, ')}px of ${clash.colWidth}px`)
  check('sharing that half at different offsets, not the same one',
    new Set(clash.contest.map((c) => c.l)).size === clash.contest.length,
    `${clash.contest.map((c) => c.l).join(', ')}`)
  check('so two appointments contesting the same hour do not cover each other',
    !clash.contestOverlap, clash.contestOverlap ? 'they overlap' : 'clear')

  // --- the phone, which is where a half-width card loses its title
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(250)
  const phone = await page.evaluate(() => {
    const out = { clipped: [], overflow: 0 }
    document.querySelectorAll('.appt-title').forEach((t) => { if (t.scrollWidth > t.clientWidth + 1) out.clipped.push(t.textContent) })
    document.querySelectorAll('*').forEach((el) => { const r = el.getBoundingClientRect(); if (r.width > 0 && r.right > window.innerWidth + 1) out.overflow += 1 })
    return out
  })
  check('on a phone the titles wrap instead of being cut off', phone.clipped.length === 0, phone.clipped.join(', ') || 'none clipped')
  check('and nothing is pushed off the side of the screen', phone.overflow === 0, `${phone.overflow} elements overflow`)
  await page.setViewportSize({ width: 1280, height: 900 })

  // --- an answer for a day you are not looking at must not be drawn on this one
  await page.route('**/api/events*', (route) => route.fulfill({ json: { day: '1999-01-01', count: mocked.length, events: mocked } }))
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(300)
  check('an answer for another day is not drawn on this one', (await page.locator('.appt').count()) === 0)

  // --- and with no calendar at all, nothing appears and no block is squeezed for it
  await page.unroute('**/api/events*')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(300)
  check('with no calendar there are no appointments, and no block is squeezed for them',
    (await page.locator('.appt').count()) === 0 && (await page.locator('.block.clash').count()) === 0,
    `${await page.locator('.block').count()} blocks still full width`)
  await page.fill('.day-head input[type="date"]', today)
  await page.waitForTimeout(400)
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
      await touchPage.locator('.tabs button[data-tab="day"]').click()
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
  await page.locator('.tabs button[data-tab="today"]').click()
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
  // naturalWidth is 0 until the file has decoded, and a slow runner makes that a race rather than
  // a check. Wait for the real size, the way everything else here waits.
  const artSized = (sel) => until(async () => {
    const box = await artOf(sel)
    return box && box.natural === RESERVED ? box : null
  })

  // 1. the empty inbox (the suite is sitting on one: nothing left, no blocks at all)
  {
    await wantTheme('light')
    await page.locator('.tabs button[data-tab="day"]').click() // the rail is the timeline's
    await until(async () => (await page.locator('.inbox').count()) === 1)
    check('the inbox really is empty before we look at it', (await inboxNow()).length === 0)
    const box = await artOf('.inbox-empty .art') // read again below once it has decoded
    check('the empty inbox shows the tray', Boolean(box) && box.width > 0, box ? `${Math.round(box.width)}px wide` : 'no .inbox-empty')
    check('and it is the light file', Boolean(box) && stem(box.src) === 'empty-inbox-light', stem(box?.src))
    const sized = await artSized('.inbox-empty .art')
    check('at the size we reserved for it', Boolean(sized), String(sized?.natural || 'never decoded'))
    check('and only one of the two files is drawn', oneImageWide(box), box ? `${Math.round(box.width)}x${Math.round(box.height)}` : 'absent')
    check('the sentence is still there to explain it', (await textOf('.inbox-empty')).includes('Nothing waiting'))
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
    await page.locator('.tabs button[data-tab="day"]').click()
    await page.fill('.day-head input[type="date"]', EMPTY_DAY)
    await until(async () => (await page.locator('.state-timeline .art').count()) === 1)

    const light = await artOf('.state-timeline .art') // read again below once it has decoded
    check('an empty timeline puts the dial on the rail', Boolean(light) && light.width > 0, light ? `${Math.round(light.width)}px wide` : 'absent')
    check('and it is the light file', Boolean(light) && stem(light.src) === 'empty-timeline-light', stem(light?.src))
    const lightSized = await artSized('.state-timeline .art')
    check('at the size we reserved for it', Boolean(lightSized), String(lightSized?.natural || 'never decoded'))
    check('and only one of the two files is drawn', oneImageWide(light), light ? `${Math.round(light.width)}x${Math.round(light.height)}` : 'absent')
    check('with the instruction still doing the explaining', (await textOf('.timeline-empty')).includes('Nothing planned yet'))
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
    await page.locator('.tabs button[data-tab="today"]').click()
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

    const all = await artOf('.state-complete .art') // read again below once it has decoded
    check('with the low sun, light file', Boolean(all) && stem(all.src) === 'day-complete-light', stem(all?.src))
    const allSized = await artSized('.state-complete .art')
    check('at the size we reserved for it', Boolean(allSized), String(allSized?.natural || 'never decoded'))
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

    // the card, at the path the page advertises for it
    const card = await page.evaluate(async () => {
      const tag = document.querySelector('meta[property="og:image"]')
      const w = document.querySelector('meta[property="og:image:width"]')
      const h = document.querySelector('meta[property="og:image:height"]')
      if (!tag) return null
      const advertised = tag.content
      const url = new URL(advertised, location.origin)
      // A deployment sets VITE_APP_URL so that crawlers, which are not on this host, get an
      // absolute address. That address is a different origin from whichever server these
      // checks are pointed at, and fetching it would be a cross-origin request that can only
      // fail — it did, and it took the run down with it. So: fetch the same *path* from the
      // server under test, and check the advertised address on its own terms.
      const here = new URL(url.pathname, location.origin).href
      const res = await fetch(here)
      const type = res.headers.get('content-type')
      // decode it: the advertised size should be the file's real size, not a hopeful label
      let real = null
      try {
        real = await createImageBitmap(await res.blob())
      } catch {
        real = null
      }
      return {
        advertised,
        here,
        absolute: url.origin !== location.origin,
        status: res.status,
        type,
        declared: `${w?.content}x${h?.content}`,
        real: real ? `${real.width}x${real.height}` : null,
        card: document.querySelector('meta[name="twitter:card"]')?.content,
      }
    })
    check(
      'the social card is served at the path the page advertises',
      card?.status === 200 && (card?.type || '').includes('jpeg'),
      `${card?.here} -> ${card?.status} ${card?.type}`,
    )
    check(
      'and the address it advertises points at that same file',
      Boolean(card) && new URL(card.advertised, 'http://x/').pathname === new URL(card.here).pathname,
      card?.absolute ? `absolute, for crawlers: ${card.advertised}` : 'relative, as a bare clone builds it',
    )
    check('and it really is 1200x630', card?.real === '1200x630', `declared ${card?.declared}, decoded ${card?.real}`)
    check('a large card, so the picture is the preview', card?.card === 'summary_large_image', String(card?.card))

    const icons = await page.evaluate(async () => {
      const paths = [
        '/favicon.svg', '/icon-32.png', '/icon-48.png', '/icon-180.png', '/icon-192.png',
        '/icon-512.png', '/apple-touch-icon.png', '/icon-maskable-192.png', '/icon-maskable-512.png',
      ]
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

    // The favicon and the PNGs are drawn by two different renderers — a browser paints the SVG,
    // Pillow draws the PNGs — so they can drift apart without either looking wrong on its own.
    // Rasterise both and compare: the same mark should come out either way.
    const agree = await page.evaluate(async () => {
      // An <img>, not createImageBitmap: that call cannot decode an SVG blob, and a failed
      // decode here used to throw out of the whole run instead of failing one check.
      const load = async (url, size) => {
        const img = new Image()
        await new Promise((resolve, reject) => {
          img.onload = resolve
          img.onerror = () => reject(new Error(`could not load ${url}`))
          img.src = url
        })
        const ctx = new OffscreenCanvas(size, size).getContext('2d')
        ctx.drawImage(img, 0, 0, size, size)
        return ctx.getImageData(0, 0, size, size).data
      }
      try {
        const size = 128
        const [a, b] = await Promise.all([load('/favicon.svg', size), load('/icon-512.png', size)])
        let sum = 0
        let far = 0
        for (let i = 0; i < a.length; i += 4) {
          const d =
            (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2])) / 3
          sum += d
          if (d > 40) far++
        }
        const n = a.length / 4
        return { mean: sum / n, farPct: (far / n) * 100 }
      } catch (err) {
        return { mean: NaN, farPct: NaN, error: String(err) }
      }
    })
    check(
      'the vector favicon and the raster icon are the same mark',
      !agree.error && agree.mean < 6 && agree.farPct < 6,
      agree.error || `mean ${agree.mean.toFixed(2)}/255, ${agree.farPct.toFixed(2)}% differing`,
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
    await page.waitForSelector('.tabs')
    // choose the day first: the artwork is the same file for every empty day, so if the
    // timeline draws once before this it is cached, the route never sees a request, and the
    // check passes without ever testing a slow connection
    await page.fill('.day-head input[type="date"]', EMPTY_DAY)
    await page.locator('.tabs button[data-tab="day"]').click()
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


// ---- keyboard, focus and the accessibility tree ---------------------------------------------
// Three separate things, because "accessible" is not one check: axe over the two main views, a
// real tab-through that measures the ring on every stop, and a look at the built stylesheet for
// anything that removes an outline. The tab-through is the one that would have caught inputs
// whose only focus cue was a border changing colour.
{
  const themeNow = () => page.evaluate(() => document.documentElement.dataset.theme)
  const wantTheme = async (want) => {
    if ((await themeNow()) !== want) {
      await page.locator('.theme-toggle').click()
      await page.waitForTimeout(200)
    }
  }

  const AXE = require.resolve('axe-core/axe.min.js')
  await page.addScriptTag({ path: AXE })
  const audit = async (label, tags) => {
    const found = await page.evaluate(
      async (tags) => {
        const res = await window.axe.run(document, {
          runOnly: { type: 'tag', values: tags },
        })
        return res.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          where: v.nodes.map((n) => n.target.join(' ')).slice(0, 3),
        }))
      },
      tags,
    )
    check(
      `${label}: no automated accessibility violations`,
      found.length === 0,
      found.length
        ? found.map((v) => `${v.id} [${v.impact}] ${v.where.join(', ')}`).join(' | ').slice(0, 320)
        : 'clean',
    )
  }
  const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']

  // No interactive control may contain another. axe's nested-interactive rule does NOT fire on
  // the pattern this app had (a div[role=button] holding a real checkbox button) — verified
  // against the released build with a row on screen, where axe reported nothing and this walk
  // reported exactly the row. So it is its own check: any widget with a focusable descendant.
  const nested = await page.evaluate(() => {
    const WIDGET = new Set(['button', 'checkbox', 'link', 'menuitem', 'option', 'radio', 'switch', 'tab', 'textbox'])
    const NATIVE = new Set(['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'])
    const focusable = (el) => NATIVE.has(el.tagName) || (el.tabIndex != null && el.tabIndex >= 0)
    const out = []
    for (const el of document.querySelectorAll('*')) {
      const role = (el.getAttribute('role') || '').toLowerCase()
      if (!(WIDGET.has(role) || NATIVE.has(el.tagName))) continue
      for (const child of el.querySelectorAll('*')) {
        if (focusable(child)) {
          out.push(
            `${el.tagName.toLowerCase()}${role ? `[role=${role}]` : ''} contains ${child.tagName.toLowerCase()}`,
          )
          break
        }
      }
    }
    return [...new Set(out)]
  })
  check(
    'no interactive control contains another',
    nested.length === 0,
    nested.length ? nested.slice(0, 3).join(' | ') : 'none on the plan view',
  )

  // the plan, where a whole day of rows is on screen
  await wantTheme('light')
  await page.locator('.tabs button[data-tab="today"]').click()
  await page.waitForTimeout(400)
  await audit('the plan, in light', TAGS)

  // the timeline, dark: a scroll region, blocks, and the amber now chip
  await page.locator('.tabs button[data-tab="day"]').click()
  await wantTheme('dark')
  await page.waitForTimeout(500)
  await audit('the timeline, in dark', TAGS)
  await wantTheme('light')
  await page.locator('.tabs button[data-tab="today"]').click()
  await page.waitForTimeout(400)

  // What does the keyboard actually see? Tab through and measure the ring at every stop: a
  // visible indicator is one that is at least 2px wide and contrasts with what is behind it.
  const focusInfo = () =>
    page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body) return null
      const nums = (c) => (c.match(/[\d.]+/g) || []).map(Number)
      const lum = ([r, g, b]) => {
        const f = (v) => {
          v /= 255
          return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
      }
      const ratio = (a, b) => {
        const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
        return (hi + 0.05) / (lo + 0.05)
      }
      // the ground the ring is drawn on: walk up until a background is actually opaque
      let ground = null
      for (let n = el; n; n = n.parentElement) {
        const c = nums(getComputedStyle(n).backgroundColor)
        if (c.length >= 3 && (c[3] === undefined || c[3] > 0.95)) {
          ground = c.slice(0, 3)
          break
        }
      }
      const cs = getComputedStyle(el)
      const cls = String(el.className || '').split(' ').filter(Boolean)[0]
      // a stable identity for the element itself, so a control that is several stops is judged once
      window.__probeIds = window.__probeIds || new WeakMap()
      if (!window.__probeIds.has(el)) window.__probeIds.set(el, (window.__probeIds.size || 0) + 1)
      return {
        key: window.__probeIds.get(el),
        what: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`,
        width: parseFloat(cs.outlineWidth) || 0,
        style: cs.outlineStyle,
        contrast:
          ground && cs.outlineStyle !== 'none'
            ? Number(ratio(nums(cs.outlineColor).slice(0, 3), ground).toFixed(2))
            : null,
      }
    })

  // Walk from the top of the page. Where sequential focus starts is not the top of the document
  // but the last thing that was clicked, and the last thing clicked to get here is a destination
  // in the tab bar — which is last in the DOM, so the walk ended after two stops and reported
  // that the keyboard reaches almost nothing. Focusing the body resets the starting point to the
  // document root; clicking dead ground is the other way, except the top-left corner of this app
  // is its date input, and clicking that opens a picker.
  await page.evaluate(() => {
    document.activeElement?.blur()
    document.body.setAttribute('tabindex', '-1')
    document.body.focus()
  })
  const stops = []
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press('Tab')
    const info = await focusInfo()
    if (!info) break
    // No "wrapped round" shortcut: identical stops in a row are legitimate and common — an
    // <input type="date"> is a stop per field, and a list is a stop per row — so comparing each
    // stop to the first one ended this walk after three. The loop cap is the only stop needed.
    stops.push(info)
  }
  check('the keyboard reaches the app controls', stops.length >= 8, `${stops.length} stops`)

  // One control can be several stops: a date field is a stop per piece, and the UA takes focus
  // into its own shadow tree, where the app's ring cannot reach and the host's outline-style
  // reads 'none'. So judge the ring once per element — a stop that is the same element as the
  // one before it is that control re-entered, not a new thing that failed to show a ring.
  const ringless = stops.filter(
    (s, i) =>
      !(i > 0 && stops[i - 1].key === s.key) &&
      (s.width < 2 || s.style === 'none' || (s.contrast ?? 99) < 3),
  )
  check(
    'and every stop shows a visible focus ring',
    ringless.length === 0,
    ringless.length
      ? ringless.map((s) => `${s.what}: ${s.width}px ${s.contrast}:1`).join(' | ')
      : `${stops.length} stops, all ringed (min contrast ${Math.min(...stops.map((s) => s.contrast ?? 99)).toFixed(1)}:1)`,
  )

  // and nothing in the built stylesheet may remove an outline: that is how the two capture
  // fields lost theirs, one `outline: none` at a time
  const css = await page.evaluate(async () => {
    const html = await (await fetch('/')).text()
    const href = (html.match(/\/assets\/index-[A-Za-z0-9._-]+\.css/) || [])[0]
    return href ? await (await fetch(href)).text() : ''
  })
  const killer = /outline\s*:\s*(none|0)\b|outline-width\s*:\s*0\b/.exec(css)
  check(
    'nothing in the stylesheet removes a focus outline',
    css.length > 0 && !killer,
    killer ? `found "${killer[0]}" in the built CSS` : 'no outline: none in the built CSS',
  )
}


const wantThemeLight = async () => {
  if ((await page.evaluate(() => document.documentElement.dataset.theme)) !== 'light') {
    await page.locator('.theme-toggle').click()
    await page.waitForTimeout(200)
  }
}

// ---- calendar sync ----------------------------------------------------------
// This suite runs against a server with no credentials, which is exactly the state a fresh
// install is in and worth pinning: an unconfigured calendar has to say how to connect
// itself, and must not look as though it holds events it has never read.
{
  await page.locator('.tabs button[data-tab="you"]').click() // the calendar lives in the profile tab now
  await page.waitForTimeout(500)

  const panel = await page.locator('.cal').innerText().catch(() => '')
  check(
    'with no credentials the calendar panel says what it needs',
    /not connected/.test(panel) && /app-specific password/.test(panel),
    panel.split('\n').filter(Boolean).slice(0, 2).join(' · '),
  )
  check(
    'and offers no Sync control that could only fail',
    (await page.locator('.cal-sync').count()) === 0,
    'no sync button while unconfigured',
  )
  check(
    'and offers one control that can actually connect it',
    (await page.locator('.cal-connect-open').count()) === 1,
    'a Connect control, rather than only a sentence about a file',
  )

  await page.locator('.cal-connect-open').click()
  const opened = await page.locator('.cal').innerText()
  check(
    'and the form it opens asks for both things, in words',
    (await page.locator('.cal-input').count()) === 2 &&
      /Apple ID/.test(opened) &&
      /App-specific password/.test(opened),
    'two fields, each under a label',
  )
  await page.locator('.cal-cancel').click()
  check(
    'and lets you back out of it',
    (await page.locator('.cal-input').count()) === 0 &&
      (await page.locator('.cal-connect-open').count()) === 1,
    'Cancel closes the form without connecting anything',
  )
  check(
    'and says what is not switched on yet, in words rather than a dead control',
    /Google Calendar — coming soon/.test(panel) &&
      (await page.locator('.cal-other button').count()) === 0,
    panel.split('\n').filter((line) => /Google/.test(line))[0] ?? 'nothing about Google',
  )
  check(
    'and shows no events, because it has never read any',
    (await page.locator('.cal-event').count()) === 0 &&
      !/Nothing on the calendar/.test(panel),
    'no rows, and no claim about an empty calendar',
  )
}

// ---- notifications ----------------------------------------------------------
// Off until it is asked for, and its own state said in words rather than as a switch position.
// Two things hold in any browser, which is why those are what get asserted instead of the
// particular state: a control is only offered when it could actually do something, and the
// limit is on screen — sundial sends these itself, so it can only send while it is running.
{
  const profile = await page.locator('.profile').innerText()
  const state = (await page.locator('.profile .push-state').innerText()).trim()
  const blocked = await page.locator('.profile .push-blocked').count()
  const toggles = await page.locator('.profile .push-toggle').count()

  check(
    'the profile says what would be notified, and when',
    /Notifications/i.test(profile) && /When a block starts/.test(profile),
    state ? `"When a block starts" · ${state}` : 'nothing about notifications',
  )
  check(
    'and names its own state in words, rather than a switch nobody can verify',
    /^(On|Off)$/.test(state),
    state || '(no state shown)',
  )
  check(
    'and offers a control only when one could actually work',
    (blocked === 1 && toggles === 0) || (blocked === 0 && toggles === 1),
    blocked
      ? 'refused by this browser, and says why instead of offering a dead control'
      : 'offered, because this browser could turn it on',
  )
  check(
    'and admits it can only send while the app is running',
    /only send while it is running/.test(profile),
    'the limit is on screen rather than discovered later',
  )
  check(
    'and promises nothing beyond the one notification',
    /no reminders, no summary/.test(profile),
    'the wording rules out the nagging it could have had',
  )
}

// ---- visual regression snapshots ------------------------------------------------------------
// Seven pictures of the app in states whose appearance is the feature: the phone agenda, desktop
// in both themes, the three empty states, and the icon under its launcher masks. Baselines are
// committed; the comparison happens in the browser (no image library in Node), and a baseline
// captured on a different platform or Chromium build is reported rather than silently passed,
// because font rasterisation genuinely differs between them.
{
  const fs = require('node:fs')
  const path = require('node:path')
  const DIR = path.join(import.meta.dirname, 'baselines')
  const META = path.join(DIR, 'meta.json')
  const HERE = `${process.platform}-${process.arch}/chromium-${browser.version()}`
  const updating = process.env.UPDATE_SNAPSHOTS === '1'
  // Set from measurement rather than taste: across clean runs the noisiest shot differed by
  // 0.27% of pixels, and the first gate written here (2.5%) let a deliberately corrupted
  // baseline through at 1.14%. These leave ~3x headroom over observed noise and still catch a
  // change to a few rows.
  const MAX_MEAN = 0.5
  const MAX_FAR_PCT = 0.8

  const shoot = async (name, prepare) => {
    await prepare()
    await page.waitForTimeout(500) // let fonts and the artwork settle
    const buffer = await page.screenshot({ fullPage: false })
    const file = path.join(DIR, `${name}.png`)

    if (updating || !fs.existsSync(file)) {
      fs.mkdirSync(DIR, { recursive: true })
      fs.writeFileSync(file, buffer)
      const meta = fs.existsSync(META) ? JSON.parse(fs.readFileSync(META, 'utf8')) : {}
      meta[name] = HERE
      fs.writeFileSync(META, `${JSON.stringify(meta, null, 2)}\n`)
      check(`${name}: baseline ${updating ? 'updated' : 'captured'}`, true, `${Math.round(buffer.length / 1024)}KB`)
      return
    }

    const captured = fs.existsSync(META) ? (JSON.parse(fs.readFileSync(META, 'utf8'))[name] || 'unknown') : 'unknown'
    if (captured !== HERE) {
      console.log(
        `  note  ${name}: not compared — baseline captured on ${captured}, this run is ${HERE}.` +
          ` Re-run with UPDATE_SNAPSHOTS=1 to re-capture here.`,
      )
      return
    }

    const diff = await page.evaluate(
      async ([was, now]) => {
        const load = async (b64) => {
          const img = new Image()
          img.src = `data:image/png;base64,${b64}`
          await img.decode()
          const c = new OffscreenCanvas(img.width, img.height)
          const ctx = c.getContext('2d')
          ctx.drawImage(img, 0, 0)
          return ctx.getImageData(0, 0, img.width, img.height)
        }
        const a = await load(was)
        const b = await load(now)
        if (a.width !== b.width || a.height !== b.height) {
          return { resized: `${a.width}x${a.height} -> ${b.width}x${b.height}` }
        }
        let sum = 0
        let far = 0
        for (let i = 0; i < a.data.length; i += 4) {
          const d =
            (Math.abs(a.data[i] - b.data[i]) +
              Math.abs(a.data[i + 1] - b.data[i + 1]) +
              Math.abs(a.data[i + 2] - b.data[i + 2])) /
            3
          sum += d
          if (d > 40) far++
        }
        const n = a.data.length / 4
        return { mean: sum / n, farPct: (far / n) * 100 }
      },
      [fs.readFileSync(file).toString('base64'), buffer.toString('base64')],
    )

    const ok = !diff.resized && diff.mean <= MAX_MEAN && diff.farPct <= MAX_FAR_PCT
    if (!ok) fs.writeFileSync(path.join(DIR, `${name}.current.png`), buffer) // inspectable
    check(
      `${name}: unchanged against its baseline`,
      ok,
      diff.resized
        ? diff.resized
        : `mean ${diff.mean.toFixed(2)}/255, ${diff.farPct.toFixed(2)}% differing` +
          (ok ? '' : ` — current shot written to ${name}.current.png`),
    )
  }

  // a fixed little day, so the pictures are of the same thing every run
  const seeded = []
  for (const [title, start, mins, color, icon] of [
    ['Standup', 9 * 60, 30, 'slate', ''],
    ['Draft the review', 10 * 60 + 30, 90, 'amber', '📝'],
    ['Walk', 19 * 60 + 30, 45, 'emerald', '🌤'],
  ]) {
    seeded.push(await spawn({ title, day: today, start_min: start, duration_min: mins, color, icon }))
  }
  const held = await spawn({ title: 'Something unscheduled', duration_min: 30 })
  // Blocks written straight to the API are not in the app's state until it looks again — it
  // fetches on mount and on a day change. Without this the first shots came out of an empty
  // plan, and a 3px change to every row compared as identical.
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(600)

  const setSize = (w, h) => page.setViewportSize({ width: w, height: h })
  const setTab = async (name) => {
    await page.locator(`.tabs button[data-tab="${name}"]`).click()
    await page.waitForTimeout(400)
  }
  const setDay = async (d) => {
    await page.fill('.day-head input[type="date"]', d)
    await page.waitForTimeout(600)
  }

  // A frozen clock, because these pictures contain the time. The header clock reads it, and
  // the timeline's scroll position follows it (half an hour before now, minus 60px), so a
  // couple of minutes of drift between two runs shifts the entire column by a couple of
  // pixels. That is not a visual change, but it is a difference — this check was passing on
  // the luck of which minute the two runs happened to land in, and 0.16% of pixels differing
  // with a mean of 1.06 is what that looks like when the luck runs out.
  //
  // Only the page is frozen; the suite's own clock keeps running.
  const SNAPSHOT_AT = new Date(`${today}T14:30:00`).toISOString()
  await page.addInitScript((stamp) => {
    const Real = Date
    const fixed = new Real(stamp).getTime()
    class FrozenDate extends Real {
      constructor(...args) {
        super(...(args.length ? args : [fixed]))
      }
      static now() {
        return fixed
      }
    }
    globalThis.Date = FrozenDate
  }, SNAPSHOT_AT)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(400)

  try {
    await wantThemeLight()
    await setDay(today)
    await setTab('today')
    await shoot('desktop-plan-light', async () => {
      await setSize(1280, 900)
      await setDay(today)
      await setTab('today')
    })
    await shoot('desktop-plan-dark', async () => {
      await setSize(1280, 900)
      await setDay(today)
      await setTab('today')
      await page.locator('.theme-toggle').click()
    })
    await page.locator('.theme-toggle').click() // back to light
    await shoot('desktop-timeline-light', async () => {
      await setSize(1280, 900)
      await setDay(today)
      await setTab('day')
    })
    await shoot('phone-plan-light', async () => {
      await setSize(390, 844)
      await setDay(today)
      await setTab('today')
    })
    await shoot('phone-empty-timeline', async () => {
      await setSize(390, 844)
      await setDay(EMPTY_DAY)
      await setTab('day')
      await until(async () => (await page.locator('.state-timeline .art').count()) === 1)
    })
    await shoot('phone-empty-inbox', async () => {
      // The inbox on a phone is the plan's Anytime section now — the rail's tray stacked above
      // the day was what this shot used to capture, and it is gone above 780px only. Same day,
      // same empty state, the place it is actually shown.
      await setSize(390, 844)
      await setDay(EMPTY_DAY)
      await setTab('today')
    })
    await shoot('phone-day-complete', async () => {
      // a genuinely finished day: everything on it done, nothing left in the inbox, and it has
      // to be TODAY — "finished" is a fact about today, not about a date
      await req(`/blocks/${held.id}`, { method: 'DELETE' }).catch(() => {})
      for (const b of seeded) {
        await req(`/blocks/${b.id}`, { method: 'PATCH', body: JSON.stringify({ done: true }) })
      }
      await setSize(390, 844)
      await page.reload({ waitUntil: 'networkidle' })
      await setDay(today)
      await setTab('today')
      await until(async () => (await page.locator('.state-complete .art').count()) === 1)
      await page.locator('.state-complete').scrollIntoViewIfNeeded()
    })
  } finally {
    await setSize(1280, 900)
    await setDay(today)
    for (const b of [...seeded, held]) {
      await req(`/blocks/${b.id}`, { method: 'DELETE' }).catch(() => {})
    }
  }

  // the icon under its launcher masks, which is platform-independent: the files are committed
  // and the masks are CSS, so there is no font rasterisation to disagree about
  {
    const sheet = await browser.newContext({ viewport: { width: 720, height: 260 }, deviceScaleFactor: 1 })
    const icons = await sheet.newPage()
    await icons.setContent(`
      <body style="margin:0;display:flex;gap:18px;align-items:center;padding:16px;background:#1b1a17">
        ${['', 'circle(50% at 50% 50%)', 'inset(0 round 34%)', 'inset(0 round 22%)']
          .map(
            (clip) =>
              `<img src="${BASE}/icon-maskable-512.png" width="128" height="128"
                 ${clip ? `style="clip-path:${clip}"` : ''}>`,
          )
          .join('')}
      </body>`)
    await icons.waitForTimeout(400)
    const buffer = await icons.screenshot()
    await sheet.close()

    const file = path.join(DIR, 'icon-masks.png')
    if (updating || !fs.existsSync(file)) {
      fs.mkdirSync(DIR, { recursive: true })
      fs.writeFileSync(file, buffer)
      const meta = fs.existsSync(META) ? JSON.parse(fs.readFileSync(META, 'utf8')) : {}
      meta['icon-masks'] = HERE
      fs.writeFileSync(META, `${JSON.stringify(meta, null, 2)}\n`)
      check(`icon-masks: baseline ${updating ? 'updated' : 'captured'}`, true, `${Math.round(buffer.length / 1024)}KB`)
    } else {
      const diff = await page.evaluate(
        async ([was, now]) => {
          const load = async (b64) => {
            const img = new Image()
            img.src = `data:image/png;base64,${b64}`
            await img.decode()
            const c = new OffscreenCanvas(img.width, img.height)
            c.getContext('2d').drawImage(img, 0, 0)
            return c.getContext('2d').getImageData(0, 0, img.width, img.height)
          }
          const a = await load(was)
          const b = await load(now)
          let sum = 0
          let far = 0
          for (let i = 0; i < a.data.length; i += 4) {
            const d =
              (Math.abs(a.data[i] - b.data[i]) +
                Math.abs(a.data[i + 1] - b.data[i + 1]) +
                Math.abs(a.data[i + 2] - b.data[i + 2])) /
              3
            sum += d
            if (d > 40) far++
          }
          const n = a.data.length / 4
          return { mean: sum / n, farPct: (far / n) * 100 }
        },
        [fs.readFileSync(file).toString('base64'), buffer.toString('base64')],
      )
      const ok = diff.mean <= MAX_MEAN && diff.farPct <= MAX_FAR_PCT
      if (!ok) fs.writeFileSync(path.join(DIR, 'icon-masks.current.png'), buffer)
      check(
        'icon-masks: unchanged against its baseline',
        ok,
        `mean ${diff.mean.toFixed(2)}/255, ${diff.farPct.toFixed(2)}% differing`,
      )
    }
  }
}


// ---- connecting from the panel --------------------------------------------------------------
// Last, because it leaves a credential file behind. The suite will not run it unless it is told
// where the server was told to keep that file: without knowing, the write lands wherever the
// server's default is — and on the box that serves sundial, that default is a real one. So a
// missing answer here is a failed check with instructions rather than a quiet clobber.
const disposableIcloud = process.env.SUNDIAL_CHECK_ICLOUD_ENV
check(
  'the suite knows where the server keeps its credentials file',
  Boolean(disposableIcloud),
  'set SUNDIAL_CHECK_ICLOUD_ENV to the same path as the server\'s SUNDIAL_ICLOUD_ENV',
)

if (disposableIcloud) {
  const fs2 = require('node:fs')
  const appleId = 'browser-check@example.com'
  const appPassword = 'not-a-real-password-a1b2'

  await page.locator('.tabs button[data-tab="you"]').click()
  await page.waitForTimeout(400)
  if ((await page.locator('.cal-connect-open').count()) > 0) {
    await page.locator('.cal-connect-open').click()
  }
  await page.locator('.cal-input').nth(0).fill(appleId)
  await page.locator('.cal-input').nth(1).fill(appPassword)
  await page.locator('.cal-save').click()

  let connected = true
  try {
    await page.waitForSelector('.cal-connect', { state: 'detached', timeout: 20000 })
  } catch {
    connected = false
  }
  check(
    'typing a credential into the panel writes it and the panel takes it',
    connected,
    await page.locator('.cal-why').innerText().catch(() => 'the form is still there'),
  )

  // What is on disk is the whole point: 0600, and the values that were typed.
  let stored = ''
  let mode = 0
  try {
    stored = fs2.readFileSync(disposableIcloud, 'utf8')
    mode = fs2.statSync(disposableIcloud).mode & 0o777
  } catch {
    stored = ''
  }
  check(
    'and the file it wrote is 0600 and holds what was typed',
    stored.includes(`ICLOUD_USERNAME=${appleId}`) &&
      stored.includes(`ICLOUD_APP_PASSWORD=${appPassword}`) &&
      mode === 0o600,
    `mode ${mode.toString(8)}, ${stored.split('\n').filter(Boolean).length} lines`,
  )

  // And not in the page: not in a field left behind, not anywhere in the DOM.
  const leftBehind = await page.evaluate(
    () =>
      [...document.querySelectorAll('input, textarea')].map((el) => el.value).join('|') +
      document.documentElement.outerHTML,
  )
  check(
    'and the password is not left in the page afterwards',
    !leftBehind.includes(appPassword),
    'not in a field, not in the markup',
  )
  check(
    'and a configured calendar offers Sync where it offered Connect',
    (await page.locator('.cal-sync').count()) === 1 &&
      (await page.locator('.cal-connect-open').count()) === 0,
    'the control that replaces it can do something',
  )

  // Put it back, like the block seeds: a check that leaves a credential behind makes the next
  // run start from a different state than this one and turns "no credentials" into a lie.
  fs2.rmSync(disposableIcloud, { force: true })
}

check('no uncaught page errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))

await browser.close()

// never leave seeds behind, even on a failing run
for (const id of made) await req(`/blocks/${id}`, { method: 'DELETE' }).catch(() => {})

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) failed`)
process.exit(failures === 0 ? 0 : 1)
