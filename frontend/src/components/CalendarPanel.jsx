import { eventTime, hasLooked, statusLine } from '../calendar.js'

/** The calendar, in the rail: what is connected, how fresh it is, and what is on this day.
 *
 * Read-only on purpose. This is context for deciding how to spend a day, not a second place
 * to manage a calendar — nothing here can move or delete an event, and the only controls are
 * ones that change what *sundial* does: sync, and show or hide a calendar.
 */
export default function CalendarPanel({ status, events, busy, note, onSync, onToggle }) {
  const configured = Boolean(status?.configured)
  const calendars = status?.calendars ?? []
  const failed = calendars.filter((c) => c.last_error)
  // Which colour belongs to which calendar, so an event can be marked with the same swatch
  // its calendar carries above. Without this the two lists read as unrelated.
  const colourOf = Object.fromEntries(calendars.map((c) => [c.ref, c.colour]))

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

      <p className="cal-when">{statusLine(status, note)}</p>

      {!configured && (
        <p className="cal-why">
          Add <code>icloud.env</code> with your Apple ID and an app-specific password.
        </p>
      )}

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
