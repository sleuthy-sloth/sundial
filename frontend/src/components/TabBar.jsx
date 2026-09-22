/**
 * Where you are: the plan, the week, the clock, the app's own settings.
 *
 * Four destinations, the same four at every width. This replaced a switch in the header plus
 * a rail beside the day, which is what put the app's plumbing — credentials, sync, theme — in
 * the same column as your plan. Text rather than glyphs, because the app's language is
 * hairlines and mono labels and it has no icon set to invent.
 *
 * Week sits second because it is the same material as Today at a longer range: what the week
 * holds, before the clock you place things on. Order is fixed rather than adaptive — a
 * navigation you have to look for is not navigation. Four labels still fit a 390px bar, one
 * per thumb-width.
 *
 * A nav of buttons, not a tablist: these are places you go, so the honest semantic is
 * aria-current rather than aria-selected. The rail still appears beside the timeline above
 * 780px, because dragging an unscheduled task onto the clock needs a source beside its target.
 */
export default function TabBar({ tab, onTab }) {
  return (
    <nav className="tabs" aria-label="Where you are">
      {[['today', 'Today'], ['week', 'Week'], ['day', 'Day'], ['you', 'You']].map(([key, label]) => (
        <button
          key={key}
          type="button"
          data-tab={key}
          aria-current={tab === key ? 'page' : undefined}
          onClick={() => onTab(key)}
        >
          {label}
        </button>
      ))}
    </nav>
  )
}
