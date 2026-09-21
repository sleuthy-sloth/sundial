import { HOUR_PX, hhmm, durText } from '../time'

/** One scheduled block. Compact when it is too short to hold two rows —
 *  a 15-minute block still has to show what it is. */
export default function Block({ block, view, isNow, selected, onPointerDown, onSelect }) {
  const shown = view ?? block
  const height = Math.max((shown.duration_min / 60) * HOUR_PX, 20)
  const compact = height < 46

  const classes = ['block', `c-${block.color}`]
  if (block.done) classes.push('done')
  if (isNow) classes.push('current')
  if (selected) classes.push('sel')
  if (compact) classes.push('compact')

  return (
    <div
      className={classes.join(' ')}
      style={{ top: (shown.start_min / 60) * HOUR_PX, height }}
      onPointerDown={(e) => onPointerDown(e, 'move', block)}
      onClick={() => onSelect(block.id)}
      onKeyDown={(e) => {
        // A div with role="button" and a tab stop is not a button: nothing happens on
        // Enter or Space until something happens on Enter or Space.
        if (e.key !== 'Enter' && e.key !== ' ') return
        e.preventDefault() // Space would otherwise scroll the timeline
        onSelect(block.id)
      }}
      role="button"
      tabIndex={0}
      aria-label={`${block.title}, ${hhmm(shown.start_min)} to ${hhmm(shown.start_min + shown.duration_min)}`}
    >
      <span className="block-time">
        {hhmm(shown.start_min)}–{hhmm(shown.start_min + shown.duration_min)}
      </span>
      <span className="block-title">
        {block.icon && <span className="block-icon">{block.icon}</span>}
        {block.title}
        {!compact && shown.duration_min >= 60 && (
          <span className="block-dur">{durText(shown.duration_min)}</span>
        )}
      </span>
      <span
        className="resize"
        onPointerDown={(e) => onPointerDown(e, 'resize', block)}
        title="Drag to change length"
      />
    </div>
  )
}
