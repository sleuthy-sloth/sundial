import { useEffect, useState } from 'react'
import { buildAgenda } from '../agenda'
import { hhmm } from '../time'
import Row from './Row'
import LedgerArt from './LedgerArt'

const COLLAPSED = 'sundial-collapsed'

/** The span a section actually covers, taken from what is in it rather than from the bucket's
 *  theoretical edges: "6:30 AM-11:30 AM" says something. */
const spanOf = (items) => {
  const timed = items.filter((b) => b.start_min != null)
  if (!timed.length) return ''
  const from = Math.min(...timed.map((b) => b.start_min))
  const to = Math.max(...timed.map((b) => b.start_min + b.duration_min))
  return `${hhmm(from)}–${hhmm(to)}`
}

export default function Agenda({
  blocks, inbox, draft, captureRef, onDraft, onCapture, onOpen, onToggle, onAddAt,
  leaving = [], settling = [], dayClear = false,
}) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(COLLAPSED) || '[]')
    } catch {
      return []
    }
  })

  useEffect(() => {
    localStorage.setItem(COLLAPSED, JSON.stringify(collapsed))
  }, [collapsed])

  const toggleSection = (key) =>
    setCollapsed((now) => (now.includes(key) ? now.filter((k) => k !== key) : [...now, key]))

  const sections = buildAgenda(blocks, inbox)

  return (
    <div className="agenda">
      <form className="capture-card" onSubmit={onCapture}>
        <input
          ref={captureRef}
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          placeholder="Add it to your list"
          aria-label="Capture a task"
        />
        <span className="group-add" aria-hidden="true">
          +
        </span>
      </form>

      {sections.map((section) => {
        const shut = collapsed.includes(section.key)
        // A row on its way out stays with the living until it has finished travelling.
        const active = section.items.filter((b) => !b.done || leaving.includes(b.id))
        const finished = section.items.filter((b) => b.done && !leaving.includes(b.id))
        const span = spanOf(active)

        return (
          <section key={section.key} className={`section section-${section.key}`}>
            <div className="group-head">
              <button type="button"
                className="group-name"
                onClick={() => toggleSection(section.key)}
                aria-expanded={!shut}
              >
                {section.label}
                <span className="group-caret"> {shut ? '\u25be' : '\u25b4'}</span>
              </button>
              {span && <span className="group-meta">{span}</span>}
              <span className="count">{active.length}</span>
              <button type="button"
                className="group-add"
                onClick={() => onAddAt(section.key)}
                title={`Add to ${section.label}`}
                aria-label={`Add to ${section.label}`}
              >
                +
              </button>
            </div>

            {!shut && (
              <div className="section-body">
                {active.map((block) => (
                  <Row
                    key={block.id}
                    block={block}
                    leaving={leaving.includes(block.id)}
                    settling={settling.includes(block.id)}
                    onOpen={onOpen}
                    onToggle={onToggle}
                  />
                ))}

                {active.length === 0 && finished.length === 0 && (
                  <button type="button" className="row empty" onClick={() => onAddAt(section.key)}>
                    {section.key === 'anytime'
                      ? 'Nothing waiting'
                      : `Nothing in the ${section.label.toLowerCase()}`}
                    <span className="group-add" aria-hidden="true">
                      +
                    </span>
                  </button>
                )}

                {/* Finished work lands here: out of the queue, counted, and still on the page.
                    It left the list, which is what a list of what is left is for — but the day
                    keeps its record, and one tap takes it back. */}
                {finished.length > 0 && (
                  <div className="done-group">
                    <div className="done-line">
                      Done
                      <span className="count">{finished.length}</span>
                    </div>
                    {finished.map((block) => (
                      <Row
                        key={block.id}
                        block={block}
                        settling={settling.includes(block.id)}
                        onOpen={onOpen}
                        onToggle={onToggle}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        )
      })}

      {/* The only place the all-clear shows. Not per section — a quiet morning is not a
          finished day — and only when the day is genuinely done (see dayIsClear in art.js). */}
      {dayClear && (
        <div className="state state-complete">
          <LedgerArt kind="complete" />
          <p className="state-line">Today is clear — everything you planned is done.</p>
        </div>
      )}
    </div>
  )
}
