import WeekStrip from './WeekStrip'
import Glyph from './Glyph'
import { monthName, weekdayName } from '../time'

export default function Header({
  day, today, tally, week, theme, error, onPickDay, onShift, onTheme,
}) {
  return (
    <header className="day-head">
      <div className="head-row">
        <button className="today-pill" onClick={() => onPickDay(today)}>Today</button>
        <span className="spacer" />
        {error && <span className="error" title={error}>offline</span>}
        <div className="head-actions">
          <button onClick={() => onShift(-1)} title="Previous day" aria-label="Previous day">‹</button>
          <button onClick={() => onShift(1)} title="Next day" aria-label="Next day">›</button>
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

      <div className="day-title-row">
        <h1 className="day-title">{weekdayName(day)}</h1>
        <div className="day-title-right">
          <span className="month">{monthName(day)}</span>
          <input
            type="date"
            value={day}
            onChange={(e) => e.target.value && onPickDay(e.target.value)}
            aria-label="Pick a date"
          />
          <span className="tally">{tally}</span>
        </div>
      </div>

      <WeekStrip days={week} day={day} today={today} onPick={onPickDay} />
    </header>
  )
}
