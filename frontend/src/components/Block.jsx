import { HOUR_PX, hhmm, durText } from '../time'
import Glyph from './Glyph'

/** One scheduled block. Compact when it is too short to hold two rows —
 *  a 15-minute block still has to show what it is. */
export default function Block({ block, view, isNow, selected, clash, onPointerDown, onSelect }) {
  const shown = view ?? block
  const height = Math.max((shown.duration_min / 60) * HOUR_PX, 20)
  const compact = height < 46

  const classes = ['block', `c-${block.color}`]
  if (block.done) classes.push('done')
  if (isNow) classes.push('current')
  if (selected) classes.push('sel')
  if (compact) classes.push('compact')
  // A calendar appointment shares this block's hour, so the block gives up half the column.
  // Drawn, not labelled: the narrowed row is the whole signal.
  if (clash) classes.push('clash')
  // A day of a routine rather than a block of your own: the hairline goes dotted, the same way
  // an appointment's does, because it is the same statement — this was not typed on this day.
  if (block.source === 'routine') classes.push('routine')

  return (
    /* A real button, not a div wearing role="button": the browser then supplies Enter, Space,
       focus and the announced role, and there is no interactive descendant to trip over (the
       resize handle below is pointer-only and not focusable — resizing has a keyboard path in
       the editor's length field, which is where a number is easier to change anyway). */
    <button
      type="button"
      className={classes.join(' ')}
      style={{ top: (shown.start_min / 60) * HOUR_PX, height }}
      data-routine={block.source === 'routine' ? '1' : undefined}
      onPointerDown={(e) => onPointerDown(e, 'move', block)}
      onClick={() => onSelect(block.id)}
      aria-label={`${block.title}, ${hhmm(shown.start_min)} to ${hhmm(shown.start_min + shown.duration_min)}`}
    >
      <span className="block-time">
        {hhmm(shown.start_min)}–{hhmm(shown.start_min + shown.duration_min)}
      </span>
      <span className="block-title">
        {block.icon && <span className="block-icon">{block.icon}</span>}
        {block.title}
        {/* The counter is worth a mark on the clock too: seeing the same hour coming round
            again is the whole point of having said it once. */}
        {block.source === 'routine' && !compact && (
          <span className="block-repeat" title="Repeats">
            <Glyph name="repeat" />
          </span>
        )}
        {!compact && shown.duration_min >= 60 && (
          <span className="block-dur">{durText(shown.duration_min)}</span>
        )}
      </span>
      <span
        className="resize"
        aria-hidden="true"
        onPointerDown={(e) => onPointerDown(e, 'resize', block)}
        title="Drag to change length"
      />
    </button>
  )
}
