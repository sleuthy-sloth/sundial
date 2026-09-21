
import { chromium } from 'playwright'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto('http://127.0.0.1:16799/', { waitUntil: 'networkidle' })
await page.waitForSelector('.tabs')
await page.locator('.tabs button[data-tab="today"]').click()
await page.waitForTimeout(400)
await page.evaluate(() => {
  document.activeElement?.blur()
  document.body.setAttribute('tabindex', '-1')
  document.body.focus()
})
const stops = []
for (let i = 0; i < 14; i++) {
  await page.keyboard.press('Tab')
  const info = await page.evaluate(() => {
    const el = document.activeElement
    if (!el || el === document.body) return null
    const cls = String(el.className || '').split(' ').filter(Boolean)[0]
    return { what: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`, style: getComputedStyle(el).outlineStyle }
  })
  if (!info) { stops.push('(nothing)'); break }
  stops.push(`${info.what}[${info.style}]`)
}
console.log(stops.length, 'stops:', stops.join(' -> '))
await browser.close()
