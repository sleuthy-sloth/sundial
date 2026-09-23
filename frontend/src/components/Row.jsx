import { hasSteps, stepsOf } from '../subtasks'
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
 *  A task's checklist is a third child, and the same rule applies to it: each step is its own
 *  button, beside the title rather than inside the button that opens the editor. The steps are
 *  drawn under the title, indented to it, and they are NOT rows of their own — nothing here is
 *  a `.block` or a `.row`, because a step is part of its task and a day that counted them
 *  separately would be a day that had stopped meaning what it says.
 *
 *  `leaving` is the row playing its exit; `settling` is it arriving in the finished list.
 *  Both are decided by App, so a reload landing mid-animation cannot cut it short. */
export default function Row({
  block, linked, leaving, settling, onOpen, onToggle, onToggleStep,
}) {
  const scheduled = block.start_min != null
  const classes = ['row', `c-${block.color}`]
  if (block.done) classes.push('done')
  if (leaving) classes.push('leaving')
  if (settling) classes.push('settling')

  const steps = stepsOf(block)

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

      {hasSteps(block) && (
        <ul className="row-steps">
          {steps.map((step) => (
            <li className={step.done ? 'row-step done' : 'row-step'} key={step.id}>
              <button
                type="button"
                className="step-notch"
                role="checkbox"
                aria-checked={step.done}
                aria-label={
                  step.done
                    ? `Mark ${step.title} not done`
                    : `Mark ${step.title} done`
                }
                onClick={() => onToggleStep(block, step)}
              />
              <span className="step-title">{step.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
