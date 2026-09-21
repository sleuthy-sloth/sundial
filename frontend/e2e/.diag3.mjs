
import { chromium } from 'playwright'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
await page.goto('http://127.0.0.1:16799/', { waitUntil: 'networkidle' })
await page.waitForSelector('.tabs')
for (const key of ['today', 'day', 'you']) {
  await page.locator(`.tabs button[data-tab="${key}"]`).click()
  await page.waitForTimeout(400)
  const info = await page.evaluate(() => ({
    contents: [...document.querySelectorAll('.content')].map((e) => e.parentElement?.className + ' > .' + e.className),
    cals: document.querySelectorAll('.cal').length,
    agenda: document.querySelectorAll('.agenda').length,
    viewChildren: [...document.querySelectorAll('.view')].map((v) => v.className + '[' + v.children.length + ']'),
  }))
  console.log(key, JSON.stringify(info))
}
await browser.close()
