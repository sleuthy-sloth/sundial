import { dowOf, dayNumOf } from '../time'

export default function WeekStrip({ days, day, today, onPick }) {
  if (!days?.length) return null
  return (
    <div className="week-strip" role="group" aria-label="Week">
      {days.map((d) => {
        const classes = ['day-pill']
        if (d.day === day) classes.push('on')
        if (d.day === today) classes.push('today')
        const busy = d.blocks > 0 ? ` · ${d.blocks} planned` : ''
        return (
          <button
            key={d.day}
            className={classes.join(' ')}
            onClick={() => onPick(d.day)}
            title={d.day + busy}
          >
            <span className="pill-dow">{dowOf(d.day)}</span>
            <span className="pill-num">{dayNumOf(d.day)}</span>
          </button>
        )
      })}
    </div>
  )
}
