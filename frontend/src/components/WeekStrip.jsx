import { dowOf, dayNumOf, durText } from '../time'

const CAP_MIN = 8 * 60 // a full-looking bar means "eight hours booked"

export default function WeekStrip({ days, day, today, onPick }) {
  if (!days?.length) return null
  return (
    <div className="week-strip" role="group" aria-label="Week">
      {days.map((d) => {
        const load = Math.min(d.minutes / CAP_MIN, 1)
        const classes = ['day-pill']
        if (d.day === day) classes.push('on')
        if (d.day === today) classes.push('today')
        return (
          <button
            key={d.day}
            className={classes.join(' ')}
            onClick={() => onPick(d.day)}
            title={`${d.blocks} block${d.blocks === 1 ? '' : 's'} · ${durText(d.minutes)} planned`}
          >
            <span className="pill-dow">{dowOf(d.day)}</span>
            <span className="pill-num">{dayNumOf(d.day)}</span>
            <span className="pill-bar">
              <i style={{ height: `${Math.round(load * 100)}%` }} />
            </span>
          </button>
        )
      })}
    </div>
  )
}
