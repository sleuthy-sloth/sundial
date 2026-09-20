import { useEffect, useState } from 'react'
import { buildAgenda } from '../agenda'
import Glyph from './Glyph'
import TaskCard from './TaskCard'

const COLLAPSED = 'sundial-collapsed'

export default function Agenda({
  blocks, inbox, draft, captureRef, onDraft, onCapture, onOpen, onToggle, onAddAt,
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
        <span className="section-add" aria-hidden="true">+</span>
      </form>

      {sections.map((section) => {
        const shut = collapsed.includes(section.key)
        return (
          <section key={section.key} className={`section section-${section.key}`}>
            <div className="section-head">
              <button className="section-pill" onClick={() => toggleSection(section.key)}>
                <Glyph name={section.glyph} />
                {section.label}
                <span className="count">({section.items.length})</span>
                <span className="caret">{shut ? '▾' : '▴'}</span>
              </button>
              <button
                className="section-add"
                onClick={() => onAddAt(section.key)}
                title={`Add to ${section.label}`}
                aria-label={`Add to ${section.label}`}
              >
                +
              </button>
            </div>

            {!shut && (
              <div className="section-body">
                {section.items.map((block) => (
                  <TaskCard
                    key={block.id}
                    block={block}
                    onOpen={() => onOpen(block.id)}
                    onToggle={() => onToggle(block)}
                  />
                ))}

                {section.items.length === 0 && (
                  <button className="card empty" onClick={() => onAddAt(section.key)}>
                    {section.key === 'anytime' ? 'Nothing waiting' : `Nothing in the ${section.label.toLowerCase()}`}
                    <span className="section-add" aria-hidden="true">+</span>
                  </button>
                )}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
