/**
 * Capture the README screenshots from the running app.
 *
 * Point it at a server with a throwaway database, so the pictures hold no real
 * data and nothing real gets seeded:
 *
 *   cd backend && SUNDIAL_DB=/tmp/sundial-shots.db \
 *     .venv/bin/python -m uvicorn app:app --port 6771 &
 *   cd frontend && npm run shots
 */
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const BASE = process.argv[2] || 'http://127.0.0.1:6771'
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/screenshots')
const today = new Date().toLocaleDateString('sv-SE')

const api = async (path, init) => {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (res.status === 204) return null
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(`${path}: ${res.status} ${JSON.stringify(body)}`)
  return body
}

const DAY = [
  { title: 'Morning routine', start_min: 390, duration_min: 30, color: 'amber', icon: '🚿' },
  { title: 'Language lesson', start_min: 435, duration_min: 20, color: 'emerald', icon: '📚' },
  { title: 'Breakfast', start_min: 480, duration_min: 30, color: 'rose', icon: '🍳' },
  { title: 'Deep work', start_min: 540, duration_min: 90, color: 'violet', icon: '💻' },
  { title: 'Lunch', start_min: 750, duration_min: 45, color: 'teal', icon: '🍽️' },
  { title: 'Dentist appointment', start_min: 840, duration_min: 60, color: 'sky', icon: '🩺' },
  { title: 'Walk', start_min: 1050, duration_min: 45, color: 'emerald', icon: '🏃' },
  { title: 'Dinner', start_min: 1140, duration_min: 60, color: 'slate', icon: '🍽️' },
  { title: 'Reading', start_min: 1230, duration_min: 30, color: 'indigo', icon: '📚' },
]

const INBOX = [
  { title: 'Refill office supplies', duration_min: 15, color: 'amber', icon: '📦' },
  { title: 'Organise documents', duration_min: 15, color: 'sky', icon: '🧾' },
  { title: 'Clean the kitchen counter', duration_min: 15, color: 'teal', icon: '🧹' },
]

const SHOTS = [
  { name: 'todo-light', view: 'todo', theme: 'light', width: 1280, height: 1420 },
  { name: 'calendar-light', view: 'calendar', theme: 'light', width: 1280, height: 1420 },
  { name: 'todo-dark', view: 'todo', theme: 'dark', width: 1280, height: 1420 },
  { name: 'phone', view: 'todo', theme: 'light', width: 390, height: 844 },
]

const made = []

async function seed() {
  for (const block of DAY) {
    const created = await api('/blocks', {
      method: 'POST',
      body: JSON.stringify({ ...block, day: today }),
    })
    made.push(created.id)
  }
  // One finished task, so the done state is visible rather than described.
  const breakfast = made[2]
  await api(`/blocks/${breakfast}`, { method: 'PATCH', body: JSON.stringify({ done: true }) })

  for (const item of INBOX) {
    const created = await api('/blocks', { method: 'POST', body: JSON.stringify(item) })
    made.push(created.id)
  }
}

async function shoot(browser, shot) {
  const context = await browser.newContext({
    viewport: { width: shot.width, height: shot.height },
    deviceScaleFactor: 2,
    locale: 'en-US',
  })
  const page = await context.newPage()
  // Set the view and theme before the app boots, so no clicking appears in the shot.
  await page.addInitScript(
    ([theme, view]) => {
      localStorage.setItem('sundial-theme', theme)
      localStorage.setItem('sundial-view', view)
    },
    [shot.theme, shot.view],
  )

  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForSelector(shot.view === 'calendar' ? '.content .block' : '.agenda')

  if (shot.view === 'calendar') {
    // Show the morning rather than wherever the clock happens to be.
    await page.evaluate(() => {
      const scroller = document.querySelector('.scroller')
      if (scroller) scroller.scrollTop = 330
    })
  }

  await page.waitForTimeout(350)
  const path = join(OUT, `${shot.name}.png`)
  await page.screenshot({ path })
  await context.close()
  console.log(`  wrote docs/screenshots/${shot.name}.png (${shot.width}x${shot.height} @2x)`)
}

async function cleanup() {
  for (const id of made.splice(0)) {
    await api(`/blocks/${id}`, { method: 'DELETE' }).catch(() => {})
  }
}

mkdirSync(OUT, { recursive: true })

const health = await fetch(`${BASE}/api/health`).catch(() => null)
if (!health?.ok) {
  console.error(`no app answering on ${BASE} — start one with a throwaway database first`)
  process.exit(1)
}

const existing = await api('/day')
if (existing.blocks.length || existing.inbox.length) {
  console.error('that database already has plans in it; point this at a throwaway one')
  process.exit(1)
}

console.log('seeding a plausible day...')
await seed()

let browser
try {
  browser = await chromium.launch()
  for (const shot of SHOTS) await shoot(browser, shot)
} finally {
  // Clear the throwaway database even if a shot failed half way, so the next run
  // does not trip over this one's leftovers.
  if (browser) await browser.close()
  await cleanup()
}

console.log('done — the throwaway database is empty again')
