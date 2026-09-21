import { durText, hhmm } from '../time'
import Glyph from './Glyph'

/** One ledger row: the time in the gutter, a slim colour edge, the title, and a square you
 *  fill. There is no icon bubble any more — the colour is the edge, and an emoji earns its
 *  place on the timeline, where it helps you pick a block out at a glance.
 *
 *  `leaving` is the row playing its exit; `settling` is it arriving in the finished list.
 *  Both are decided by App, so a reload landing mid-animation cannot cut it short. */
export default function Row({ block, linked, leaving, settling, onOpen, onToggle }) {
  const scheduled = block.start_min != null
  const classes = ['row', `c-${block.color}`]
  if (block.done) classes.push('done')
  if (leaving) classes.push('leaving')
  if (settling) classes.push('settling')

  return (
    <div
      className={classes.join(' ')}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(block.id)}
      onKeyDown={(e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return
        e.preventDefault()
        onOpen(block.id)
      }}
      aria-label={`${block.title}${scheduled ? `, ${hhmm(block.start_min)}` : ''}`}
    >
      <span className="row-time">{scheduled ? hhmm(block.start_min) : ''}</span>

      <button
        className="notch"
        role="checkbox"
        aria-checked={block.done}
        aria-label={`Mark ${block.title} done`}
        onClick={(e) => {
          e.stopPropagation()
          onToggle(block)
        }}
      />

      <span className="row-edge" />

      <span className="row-body">
        <span className="row-title">{block.title}</span>
        <span className="row-meta">
          {linked && (
            <span className="row-link" title="Linked to a calendar event">
              <Glyph name="link" />
            </span>
          )}
          {scheduled
            ? durText(block.duration_min)
            : durText(block.duration_min)}
        </span>
      </span>
    </div>
  )
}
