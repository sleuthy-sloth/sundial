import { version } from '../../package.json'

import { ROLLOVER_OPTIONS } from '../rollover'
import CalendarPanel from './CalendarPanel'
import Notifications from './Notifications'
import Routines from './Routines'
import Switch from './Switch'
import YourData from './YourData'

/**
 * The app's own settings, in a tab of their own rather than in a column beside your day.
 *
 * Connecting a calendar was the complaint that started this: it sat under the inbox in the
 * rail, so the app's plumbing read as part of the plan. Everything here answers a question
 * about this copy of the app, not about the day — which is why the day's events stay on the
 * Day tab, drawn on the clock, and only the connection is managed here.
 *
 * The theme also lives in the header, as a small ambient control beside the time. A setting
 * you reach for mid-task and a setting you go looking for are different things; this is the
 * second one, and it says out loud what the header's sun/moon only shows.
 *
 * Routines are here for the same reason and one more: a rule with no day on screen this week
 * has nothing to tap, so the place that lists what this copy holds is the only way back to it.
 *
 * "Unfinished scheduled work" is a setting rather than a control on the day, even though the day is
 * where it shows: it is a decision about what the app may do on its own, and a decision like that
 * belongs where you go looking for it rather than under the thing it acts on.
 */
export default function Profile({
  status,
  events,
  busy,
  note,
  onSync,
  onToggle,
  onConnect,
  connecting,
  theme,
  onTheme,
  routines,
  onOpenRoutine,
  rollover,
  onRollover,
}) {
  return (
    <div className="profile">
      <h2>Calendars</h2>
      <CalendarPanel
        status={status}
        events={events}
        busy={busy}
        note={note}
        onSync={onSync}
        onToggle={onToggle}
        onConnect={onConnect}
        connecting={connecting}
      />
      <p className="note">
        Read-only on purpose: the calendar comes in, and nothing goes back out.
      </p>

      <Routines routines={routines} onOpen={onOpenRoutine} />

      <h2>Unfinished work</h2>
      {/* Three answers to one question, so three radios rather than a switch: a switch would have
          to leave one of the answers unnamed. The labels are the whole interface — there is no
          "advanced" behind them, and no default hidden from the person choosing it. */}
      <fieldset className="set-choice">
        <legend className="set-label">Unfinished scheduled work</legend>
        {ROLLOVER_OPTIONS.map((option) => (
          <label key={option.value} className="choice">
            <input
              type="radio"
              name="rollover"
              value={option.value}
              checked={rollover === option.value}
              onChange={() => onRollover(option.value)}
            />
            <span className="choice-label">{option.label}</span>
          </label>
        ))}
      </fieldset>
      <p className="note">
        Only your own unfinished blocks count — never a calendar event, and never a day of a
        routine. Nothing is called late, and nothing is written to a day you have already had.
      </p>

      <h2>Appearance</h2>
      <div className="set-row">
        <span className="set-label">Theme</span>
        <span className="set-value">{theme}</span>
        {/* The header keeps its quick toggle; this is the same setting stated as a setting.
            A distinct class from that button, or the two controls are one selector. */}
        <Switch
          className="theme-switch"
          checked={theme === 'dark'}
          onChange={onTheme}
          label="Dark theme"
        />
      </div>

      <Notifications />

      <YourData />

      <h2>This copy</h2>
      <div className="set-row">
        <span className="set-label">Version</span>
        <span className="set-value">{version}</span>
      </div>
      <p className="note">Self-hosted, single-user, and it holds one day at a time.</p>
    </div>
  )
}
