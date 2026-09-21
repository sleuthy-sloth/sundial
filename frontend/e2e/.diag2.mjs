
import { chromium } from 'playwright'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const errs = []
page.on('pageerror', (e) => errs.push('pageerror: ' + String(e).split('\n')[0]))
page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 200)) })
await page.goto('http://127.0.0.1:16799/', { waitUntil: 'networkidle' })
await page.waitForTimeout(600)
console.log('errors:', errs.length ? errs.join('\n  ') : 'none')
console.log(await page.evaluate(() => ({
  root: document.getElementById('root')?.childElementCount,
  tabs: document.querySelectorAll('.tabs button').length,
  html: document.getElementById('root')?.innerHTML.slice(0, 300),
})))
await browser.close()
