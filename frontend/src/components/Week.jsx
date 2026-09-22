import { dayNumOf } from '../time'
import { barOf, compact, daySentence, emptyDay, shortDow, weekDays, weekTitle } from '../week'

/** The week as capacity rather than as a calendar grid.
 *
 *  A grid would say when things are; this says how much of each day is spoken for and how much
 *  is left, which is the question a week is actually read to answer. Seven columns, each with
 *  the day's planned time over its open time and a bar for the share that is taken.
 *
 *  Nothing here is a warning. A day with nothing on it is a full day, open — a dash where a
 *  figure would be, never a zero and never a note about it. Tapping a day opens it in Today,
 *  which is the only thing a day column does.
 *
 *  The arrow keys walk the columns, because a row of buttons that can only be reached by
 *  tabbing through all seven is a row that punishes the keyboard for being used.
 */
export default function Week({ days = [], anchor, today, onPickDay, onShiftWeek }) {
  const week = weekDays(anchor)
  const byDay = new Map(days.map((d) => [d.day, d]))

  const onKeyDown = (event, index) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    event.preventDefault()
    // Asked of the DOM rather than held in refs: the columns are one list, and the neighbour of
    // the third is whoever the third is next to.
    const columns = event.currentTarget.closest('.week-grid')?.querySelectorAll('.week-day')
    columns?.[index + step]?.focus()
  }

  return (
    <div className="week">
      <div className="week-head">
        <button
          type="button"
          className="week-step"
          onClick={() => onShiftWeek(-7)}
          title="Previous week"
          aria-label="Previous week"
        >
          {'\u2039'}
        </button>
        <h2 className="week-label">{weekTitle(anchor)}</h2>
        <button
          type="button"
          className="week-step"
          onClick={() => onShiftWeek(7)}
          title="Next week"
          aria-label="Next week"
        >
          {'\u203a'}
        </button>
      </div>

      <ol className="week-grid">
        {week.map((iso, index) => {
          // A day the week could not read is drawn as what it is: nothing planned, all of it
          // open. Not as the previous week's numbers, and not as a gap in the week.
          const day = byDay.get(iso) ?? emptyDay(iso)
          const bar = barOf(day)
          const isToday = iso === today
          const classes = ['week-day']
          if (isToday) classes.push('is-today')
          if (iso === anchor) classes.push('is-here')

          return (
            <li key={iso}>
              <button
                type="button"
                className={classes.join(' ')}
                data-day={iso}
                aria-current={isToday ? 'date' : undefined}
                aria-label={daySentence(day, today)}
                onClick={() => onPickDay(iso)}
                onKeyDown={(event) => onKeyDown(event, index)}
              >
                <span className="week-dow">{shortDow(iso)}</span>
                <span className="week-date">{dayNumOf(iso)}</span>
                <span className="week-planned">{compact(day.planned_minutes)}</span>
                {/* Three widths that add up to the busy share of the day: your plan, the hour
                    both of them claim, and the calendar's own — never the two totals stacked. */}
                <span className="week-bar" aria-hidden="true">
                  <span className="week-fill is-plan" style={{ width: bar.plan }} />
                  <span className="week-fill is-both" style={{ width: bar.both }} />
                  <span className="week-fill is-calendar" style={{ width: bar.calendar }} />
                </span>
                <span className="week-open">
                  <span className="week-open-n">{compact(day.open_minutes)}</span>
                  <span className="week-open-word">open</span>
                </span>
                {day.block_count > 0 && (
                  <span className="week-count">
                    {day.block_count === 1 ? '1 block' : `${day.block_count} blocks`}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ol>

      <p className="note week-note">
        What each day holds, and what is left of it. A day opens in Today when you tap it.
      </p>
    </div>
  )
}
