import { useState } from 'react'

import { eventTime, hasLooked, providerNote, statusLine } from '../calendar.js'

/** The calendar, in the rail: what is connected, how fresh it is, and what is on this day.
 *
 * Read-only on purpose. This is context for deciding how to spend a day, not a second place
 * to manage a calendar — nothing here can move or delete an event, and the only controls are
 * ones that change what *sundial* does: sync, and show or hide a calendar.
 */
export default function CalendarPanel({
  status,
  events,
  busy,
  note,
  onSync,
  onToggle,
  onConnect,
  connecting,
}) {
  const configured = Boolean(status?.configured)
  const calendars = status?.calendars ?? []
  const failed = calendars.filter((c) => c.last_error)
  // Which colour belongs to which calendar, so an event can be marked with the same swatch
  // its calendar carries above. Without this the two lists read as unrelated.
  const colourOf = Object.fromEntries(calendars.map((c) => [c.ref, c.colour]))
  // Providers other than the one that ships, so the panel can be honest about them without
  // pretending they are usable yet. iCloud is the app's own state above, not a line here.
  const others = (status?.providers ?? []).filter((p) => p.provider !== 'icloud')

  // The only secret this app is ever handed, so it lives here and nowhere else: not in the
  // app's state, not in a store, not anywhere it could be painted back by accident.
  const [open, setOpen] = useState(false)
  const [appleId, setAppleId] = useState('')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setProblem('')
    // Returns a sentence when it did not work, and the box keeps what was typed so a typo in
    // one field does not mean pasting the other one again.
    const answer = await onConnect('icloud', {
      ICLOUD_USERNAME: appleId,
      ICLOUD_APP_PASSWORD: password,
    })
    if (answer) {
      setProblem(answer)
      return
    }
    setPassword('')
    setOpen(false)
  }

  return (
    <section className="cal" aria-labelledby="cal-heading">
      <div className="cal-head">
        <h2 className="cal-title" id="cal-heading">Calendar</h2>
        {configured && (
          <button type="button" className="cal-sync" onClick={() => onSync()} disabled={busy}>
            {busy ? 'Syncing…' : 'Sync'}
          </button>
        )}
      </div>

      {/* Live, because a sync that failed and a sync that finished land in the same line and
          the difference is the whole point of it. */}
      <p className="cal-when" role="status">{statusLine(status, note)}</p>

      {!configured && (
        <div className="cal-connect">
          <p className="cal-why">
            Needs an Apple ID and an app-specific password from appleid.apple.com.
          </p>
          {open ? (
            <form className="cal-form" onSubmit={submit}>
              <label className="cal-field">
                <span className="cal-label">Apple ID</span>
                <input
                  className="cal-input"
                  type="text"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck="false"
                  value={appleId}
                  onChange={(event) => setAppleId(event.target.value)}
                  required
                />
              </label>
              <label className="cal-field">
                <span className="cal-label">App-specific password</span>
                <input
                  className="cal-input"
                  type="password"
                  autoComplete="new-password"
                  autoCapitalize="none"
                  spellCheck="false"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              <div className="cal-actions">
                <button type="submit" className="cal-save" disabled={connecting}>
                  {connecting ? 'Connecting…' : 'Save'}
                </button>
                <button type="button" className="cal-cancel" onClick={() => setOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button type="button" className="cal-connect-open" onClick={() => setOpen(true)}>
              Connect
            </button>
          )}
          {problem && (
            <p className="cal-problem" role="alert">{problem}</p>
          )}
        </div>
      )}

      {others.map((p) => (
        <p className="cal-other" key={p.provider}>{providerNote(p)}</p>
      ))}

      {failed.map((c) => (
        <p className="cal-problem" key={c.ref}>{c.name}: {c.last_error}</p>
      ))}

      {/* Everything below is stored, not live: it is shown whether or not syncing is
          possible right now, because losing the credentials file must not look like
          losing the calendar. */}
      {calendars.length > 0 && (
        <ul className="cal-cals">
          {calendars.map((c) => (
            <li className={`cal-cal${c.enabled ? '' : ' is-off'}`} key={c.ref}>
              <span className={`cal-swatch c-${c.colour}`} aria-hidden="true" />
              <span className="cal-cname">{c.name}</span>
              <button
                type="button"
                className="cal-toggle"
                aria-pressed={Boolean(c.enabled)}
                onClick={() => onToggle(c.ref, !c.enabled)}
              >
                {c.enabled ? 'shown' : 'hidden'}
              </button>
            </li>
          ))}
        </ul>
      )}

      {(events.length > 0 || hasLooked(status)) && (
        <ul className="cal-events">
          {events.length === 0 ? (
            <li className="cal-empty">Nothing on the calendar.</li>
          ) : (
            events.map((e) => (
              <li className="cal-event" key={`${e.id}@${e.start_utc}`}>
                <span className="cal-time">{eventTime(e)}</span>
                <span
                  className={`cal-swatch c-${colourOf[e.calendar_ref] ?? 'slate'}`}
                  aria-hidden="true"
                />
                <span className="cal-what">{e.title}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </section>
  )
}
