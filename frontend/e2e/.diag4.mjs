
import { chromium } from 'playwright'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto('http://127.0.0.1:16799/', { waitUntil: 'networkidle' })
await page.waitForSelector('.tabs')
for (const key of ['today', 'day', 'you']) {
  await page.locator(`.tabs button[data-tab="${key}"]`).click()
  await page.waitForTimeout(400)
  await page.evaluate(() => document.activeElement?.blur())
  const stops = []
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press('Tab')
    const info = await page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body) return null
      return `${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ').filter(Boolean).slice(0, 2).join('.')}`
    })
    if (!info) { stops.push('(nothing)'); break }
    stops.push(info)
  }
  console.log(key.padEnd(6), stops.join(' -> '))
}
await browser.close()
