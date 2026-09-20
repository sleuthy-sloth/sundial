import { durText, clockText } from '../time'
import Glyph from './Glyph'

// Icon-circle tints, picked from the block's colour so a card keeps its identity.
const CIRCLE = {
  slate: 'circle-blue',
  sky: 'circle-blue',
  violet: 'circle-purple',
  amber: 'circle-orange',
  emerald: 'circle-green',
  rose: 'circle-rose',
  teal: 'circle-green',
  indigo: 'circle-purple',
}

export default function TaskCard({ block, linked, onOpen, onToggle }) {
  const scheduled = block.start_min != null
  return (
    <button className={`card${block.done ? ' done' : ''}`} onClick={onOpen}>
      <span className={`card-icon ${CIRCLE[block.color] || 'circle-blue'}`}>
        {block.icon || '·'}
      </span>

      <span className="card-main">
        <span className="card-title">{block.title}</span>
        <span className="card-meta">
          {linked && (
            <span className="card-link" title="Linked to a calendar event">
              <Glyph name="link" />
            </span>
          )}
          {scheduled
            ? `${clockText(block.start_min)} → ${clockText(block.start_min + block.duration_min)}`
            : durText(block.duration_min)}
        </span>
      </span>

      <span
        className={`tick${block.done ? ' on' : ''}`}
        role="checkbox"
        aria-checked={block.done}
        aria-label={`Mark ${block.title} done`}
        onClick={(e) => {
          e.stopPropagation()
          onToggle()
        }}
      />
    </button>
  )
}
