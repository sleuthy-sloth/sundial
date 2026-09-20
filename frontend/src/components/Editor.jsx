import { ICONS } from '../icons'
import { durText, hhmm } from '../time'

const COLORS = ['slate', 'sky', 'violet', 'amber', 'emerald', 'rose', 'teal', 'indigo']

export default function Editor({ block, today, onChange, onRemove, onClose }) {
  return (
    <aside className="editor" role="dialog" aria-label="Block details">
      <div className="sheet-grip" />

      <div className="editor-head">
        <input
          className="title-input"
          value={block.title}
          onChange={(e) => onChange({ title: e.target.value || 'Untitled' })}
          aria-label="Title"
        />
        <button className="close" onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <label className="field">
        <span>Icon</span>
        <div className="icon-grid">
          <button
            className={`icon-pick${block.icon ? '' : ' on'}`}
            onClick={() => onChange({ icon: '' })}
            aria-label="No icon"
          >
            –
          </button>
          {ICONS.map((glyph) => (
            <button
              key={glyph}
              className={`icon-pick${block.icon === glyph ? ' on' : ''}`}
              onClick={() => onChange({ icon: glyph })}
              aria-label={`Icon ${glyph}`}
            >
              {glyph}
            </button>
          ))}
        </div>
      </label>

      <label className="field">
        <span>Starts</span>
        <div className="dur-row">
          <input
            type="time"
            value={block.start_min == null ? '' : hhmm(block.start_min)}
            onChange={(e) => {
              const [h, m] = e.target.value.split(':').map(Number)
              if (Number.isFinite(h)) {
                onChange({ day: block.day ?? today, start_min: h * 60 + m })
              }
            }}
            aria-label="Start time"
          />
          {block.start_min != null && (
            <button type="button" onClick={() => onChange({ unschedule: true })}>
              Back to anytime
            </button>
          )}
        </div>
      </label>

      <label className="field">
        <span>Length</span>
        <div className="dur-row">
          <input
            type="range"
            min="5"
            max="480"
            step="5"
            value={block.duration_min}
            onChange={(e) => onChange({ duration_min: Number(e.target.value) })}
          />
          <b>{durText(block.duration_min)}</b>
        </div>
      </label>

      <label className="field">
        <span>Colour</span>
        <div className="swatches">
          {COLORS.map((c) => (
            <button
              key={c}
              className={`swatch c-${c}${block.color === c ? ' on' : ''}`}
              onClick={() => onChange({ color: c })}
              aria-label={c}
            />
          ))}
        </div>
      </label>

      <label className="field">
        <span>Notes</span>
        <textarea rows="3" value={block.notes} onChange={(e) => onChange({ notes: e.target.value })} />
      </label>

      <div className="editor-actions">
        {block.day === null ? (
          <span className="muted">In the inbox — drag it onto the timeline.</span>
        ) : (
          <button onClick={() => onChange({ unschedule: true })}>Back to inbox</button>
        )}
        <button className={block.done ? 'primary' : ''} onClick={() => onChange({ done: !block.done })}>
          {block.done ? 'Done' : 'Mark done'}
        </button>
        <button className="danger" onClick={onRemove}>Delete</button>
      </div>
    </aside>
  )
}
