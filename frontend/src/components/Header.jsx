import WeekStrip from './WeekStrip'

export default function Header({
  day, today, dayName, tally, week, theme, error, onPickDay, onShift, onTheme,
}) {
  return (
    <header className="day-head">
      <div className="day-nav">
        <button onClick={() => onShift(-1)} title="Previous day" aria-label="Previous day">‹</button>
        <button className="day-label" onClick={() => onPickDay(today)} title="Jump to today">
          {dayName}
        </button>
        <button onClick={() => onShift(1)} title="Next day" aria-label="Next day">›</button>
        <input
          type="date"
          value={day}
          onChange={(e) => e.target.value && onPickDay(e.target.value)}
          aria-label="Pick a date"
        />
        <span className="tally">{tally}</span>
        <button
          className="theme-toggle"
          onClick={onTheme}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          aria-label="Switch theme"
        >
          {theme === 'dark' ? '☾' : '☀'}
        </button>
        {error && <span className="error" title={error}>offline</span>}
      </div>
      <WeekStrip days={week} day={day} today={today} onPick={onPickDay} />
    </header>
  )
}
