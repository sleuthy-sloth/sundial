import { durText } from '../time'

export default function Inbox({ items, draft, selectedId, onDraft, onCapture, onPointerDown, onSelect }) {
  return (
    <>
      <form onSubmit={onCapture} className="capture">
        <input
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          placeholder="Dump it here, press Enter"
          aria-label="Capture a task"
        />
      </form>

      <div className="side-head">
        Inbox {items.length > 0 && <span className="count">{items.length}</span>}
      </div>

      <ul className="inbox">
        {items.length === 0 && (
          <li className="empty">Nothing waiting. Everything has a time.</li>
        )}
        {items.map((b) => (
          <li
            key={b.id}
            className={`chip c-${b.color}${selectedId === b.id ? ' sel' : ''}`}
            onPointerDown={(e) => onPointerDown(e, 'schedule', b)}
            onClick={() => onSelect(b.id)}
          >
            <span className="chip-title">
              {b.icon && <span className="block-icon">{b.icon}</span>}
              {b.title}
            </span>
            <span className="chip-dur">{durText(b.duration_min)}</span>
          </li>
        ))}
      </ul>

      {items.length > 0 && <p className="hint">Drag onto the timeline to give it a time.</p>}
    </>
  )
}
