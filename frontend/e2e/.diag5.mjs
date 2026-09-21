
import { chromium } from 'playwright'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto('http://127.0.0.1:16799/', { waitUntil: 'networkidle' })
await page.waitForSelector('.tabs')
await page.locator('.tabs button[data-tab="today"]').click()
await page.waitForTimeout(400)
console.log(await page.evaluate(() => {
  const sel = 'a[href], button, input, select, textarea, [tabindex]'
  const all = [...document.querySelectorAll(sel)]
  const vis = all.filter((el) => {
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'
  })
  return {
    total: all.length,
    visible: vis.length,
    firstTen: vis.slice(0, 10).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute('class') ?? '-'}] "${(el.textContent || el.value || '').trim().slice(0, 14)}" tabindex=${el.getAttribute('tabindex') ?? '-'}`),
  }
}))
await browser.close()
