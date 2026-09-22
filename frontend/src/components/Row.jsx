import { durText, hhmm } from '../time'
import Glyph from './Glyph'

/** One ledger row: the time in the gutter, a slim colour edge, the title, and a square you
 *  fill. There is no icon bubble any more — the colour is the edge, and an emoji earns its
 *  place on the timeline, where it helps you pick a block out at a glance.
 *
 *  Two SIBLING controls, never nested: the square is a checkbox and the rest of the row is a
 *  button that opens the editor. A row that is itself a button containing a checkbox button is
 *  invalid — a screen reader cannot announce a control inside a control, and no keyboard reaches
 *  the inner one in some browsers. So the row is a plain container and both controls are its
 *  children, side by side, with the open button's own text as its name.
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
    <div className={classes.join(' ')} data-routine={block.source === 'routine' ? '1' : undefined}>
      <button
        type="button"
        className="notch"
        role="checkbox"
        aria-checked={block.done}
        aria-label={block.done ? `Mark ${block.title} not done` : `Mark ${block.title} done`}
        onClick={() => onToggle(block)}
      />

      <button type="button" className="row-open" onClick={() => onOpen(block.id)}>
        <span className="row-time">{scheduled ? hhmm(block.start_min) : ''}</span>
        <span className="row-edge" />
        <span className="row-body">
          <span className="row-title">{block.title}</span>
          <span className="row-meta">
            {linked && (
              <span className="row-link" title="Linked to a calendar event">
                <Glyph name="link" />
              </span>
            )}
            {/* A repeating block is worth saying out loud on the list, where there is no
                column to give it away: the same title comes back tomorrow. */}
            {block.source === 'routine' && (
              <span className="row-link row-repeat" title="Repeats">
                <Glyph name="repeat" />
              </span>
            )}
            {durText(block.duration_min)}
          </span>
        </span>
      </button>
    </div>
  )
}
