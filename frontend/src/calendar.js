/** What the calendar panel says. Pure, so the wording is testable rather than eyeballed.
 *
 * The rule throughout: an empty answer is a sentence, not a blank. "Never synced" and
 * "Nothing on the calendar" both have to be sayable, because they are different facts and
 * a person looking at a blank space cannot tell which one they are in.
 */

import { hhmm } from './time.js'

export function clock(iso) {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return hhmm(at.getHours() * 60 + at.getMinutes())
}

export function eventTime(event) {
  return event.all_day ? 'all day' : clock(event.start_utc)
}

/** "just now", "12 min ago", "3 h ago", "2 days ago" — or nothing at all, which the
 *  interface reads as never. An unparseable stamp says nothing rather than "Invalid Date". */
export function ago(iso, now = Date.now()) {
  const at = new Date(iso).getTime()
  if (!iso || Number.isNaN(at)) return ''
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

/** What a sync did, in a few words. Silence when it did nothing: a sync that found
 *  nothing new should not announce itself every fifteen minutes. */
export function syncNote(result) {
  const totals = result?.totals
  if (!totals || result?.skipped) return ''
  const bits = []
  if (totals.added) bits.push(`${totals.added} new`)
  if (totals.updated) bits.push(`${totals.updated} updated`)
  if (totals.removed) bits.push(`${totals.removed} removed`)
  if (totals.errors) bits.push(`${totals.errors} failed`)
  return bits.join(' · ')
}

/** The panel's one-line state, given whatever the API last said. `now` is a parameter so
 *  the wording can be tested without waiting for a clock to move. */
export function statusLine(status, note = '', now = Date.now()) {
  if (!status) return 'checking…'
  const when = ago(status.last_sync, now)
  const parts = []
  if (!status.configured) {
    // Not being able to sync now says nothing about whether a sync ever happened: what is
    // stored stays stored, and a panel that hides it would look like the data was lost.
    parts.push('not connected')
    if (when) parts.push(`last synced ${when}`)
  } else {
    parts.push(when ? `synced ${when}` : 'never synced')
  }
  if (note) parts.push(note)
  return parts.join(' · ')
}

/** How a provider that is not the one shipping should read.
 *
 * Google is built and tested end to end and deliberately not switched on in the interface:
 * the step nobody can skip is a person walking Google's own console, so the panel says
 * "coming soon" rather than offering a button whose only outcome is a failure. Configured,
 * it says what it is instead — the honest state either way, and no dead control.
 */
export function providerNote(provider) {
  const name = provider?.provider === 'google' ? 'Google Calendar' : (provider?.provider ?? '')
  if (!name) return ''
  if (provider.last_error) return `${name} — ${provider.last_error}`
  if (!provider.configured) return `${name} — coming soon.`
  return provider.account ? `${name} — connected as ${provider.account}` : `${name} — connected`
}

/** Whether the panel has ever looked at a calendar: it can say "nothing on the calendar"
 *  only once something has been read. Before that, blank is the honest state. */
export function hasLooked(status) {
  return Boolean(status?.last_sync) || (status?.calendars ?? []).length > 0
}
