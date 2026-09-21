import { useRef } from 'react'
import { shortDate } from '../time'
import Glyph from './Glyph'

/** The day, then the controls, then the reading. The weekday is a compact label rather than a
 *  headline, and the view switch is a labelled control here instead of a capsule floating over
 *  the content it covers. */
export default function Header({
  day, today, clock, tally, view, theme, error, onPickDay, onShift, onView, onTheme,
}) {
  // The day name opens the picker instead of a second control repeating the same date next to
  // it. showPicker is not everywhere, so where it is missing the input stays on screen.
  const picker = useRef(null)
  const canPick = typeof HTMLInputElement !== 'undefined' && 'showPicker' in HTMLInputElement.prototype

  return (
    <header className="day-head">
      <input
        ref={picker}
        type="date"
        className={canPick ? 'date-quiet' : ''}
        value={day}
        onChange={(e) => e.target.value && onPickDay(e.target.value)}
        aria-label="Pick a date"
      />
      <div className="head-row">
        <button className="step" onClick={() => onShift(-1)} title="Previous day" aria-label="Previous day">
          {'\u2039'}
        </button>
        <button
          className="day-id"
          onClick={() => canPick && picker.current?.showPicker()}
          title="Pick a date"
          aria-label={`Change the day, currently ${shortDate(day)}`}
        >
          <span className="day-name">{shortDate(day)}</span>
        </button>
        <span className="day-clock">{clock}</span>
        <button className="step" onClick={() => onShift(1)} title="Next day" aria-label="Next day">
          {'\u203a'}
        </button>

        {day !== today && (
          <button className="today-pill" onClick={() => onPickDay(today)}>
            Today
          </button>
        )}

        <span className="spacer" />

        <div className="view-switch" role="group" aria-label="View">
          <button aria-pressed={view === 'todo'} onClick={() => onView('todo')}>
            Plan
          </button>
          <button aria-pressed={view === 'calendar'} onClick={() => onView('calendar')}>
            Timeline
          </button>
        </div>
      </div>

      <div className="head-row">
        <span className="tally">{tally}</span>
        <span className="spacer" />
        {error && (
          <span className="error" title={error}>
            offline
          </span>
        )}
        <div className="head-actions">
          <button
            className="theme-toggle"
            onClick={onTheme}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            aria-label="Switch theme"
          >
            <Glyph name={theme === 'dark' ? 'moon' : 'sun'} />
          </button>
        </div>
      </div>
    </header>
  )
}
