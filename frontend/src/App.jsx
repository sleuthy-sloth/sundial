import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, hhmm, durText, shiftDay, dayLabel,
} from './time'

const COLORS = ['slate', 'sky', 'violet', 'amber', 'emerald', 'rose', 'teal', 'indigo']
const HOURS = Array.from({ length: 24 }, (_, h) => h)

export default function App() {
  const [day, setDay] = useState(todayISO())
  const [today, setToday] = useState(todayISO())
  const [blocks, setBlocks] = useState([])
  const [inbox, setInbox] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [nowMin, setNowMin] = useState(minsNow())
  const [drag, setDrag] = useState(null)
  const [ghost, setGhost] = useState(null)

  const contentRef = useRef(null)
  const scrollerRef = useRef(null)
  const ghostRef = useRef(null) // mirrors `ghost` so pointerup reads the live value
  const movedRef = useRef(false)

  const load = useCallback(async () => {
    try {
      const data = await api.day(day)
      setBlocks(data.blocks)
      setInbox(data.inbox)
      setToday(data.today)
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }, [day])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const t = setInterval(() => setNowMin(minsNow()), 30_000)
    return () => clearInterval(t)
  }, [])

  // Land somewhere useful: half an hour before now, else 7am.
  useEffect(() => {
    if (!scrollerRef.current) return
    const focusMin = day === todayISO() ? nowMin - 30 : 7 * 60
    scrollerRef.current.scrollTop = Math.max(0, (focusMin / 60) * HOUR_PX - 60)
  }, [day]) // eslint-disable-line react-hooks/exhaustive-deps

  const setGhostValue = (g) => { ghostRef.current = g; setGhost(g) }

  // ---- dragging: one pointer handler for move, resize and inbox→timeline ----

  const beginDrag = (e, mode, block) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = contentRef.current.getBoundingClientRect()
    const grabbedMin = ((e.clientY - rect.top) / HOUR_PX) * 60
    movedRef.current = false
    ghostRef.current = null
    setGhost(null)
    setSelectedId(block.id)
    setDrag({
      mode,
      id: block.id,
      title: block.title,
      duration: block.duration_min,
      start_min: block.start_min ?? 0,
      grabOffset: mode === 'move' ? grabbedMin - block.start_min : 0,
      originX: e.clientX,
      originY: e.clientY,
    })
  }

  useEffect(() => {
    if (!drag) return
    const onMove = (ev) => {
      const rect = contentRef.current?.getBoundingClientRect()
      if (!rect) return
      // Distance from the grab point, not movementX/Y: those are zero on the
      // first event and on some platforms, and a click must not read as a drag.
      const travelled = Math.hypot(ev.clientX - drag.originX, ev.clientY - drag.originY)
      movedRef.current = movedRef.current || travelled > 3
      const yMin = ((ev.clientY - rect.top) / HOUR_PX) * 60
      const inside =
        ev.clientY >= rect.top && ev.clientY <= rect.bottom &&
        ev.clientX >= rect.left && ev.clientX <= rect.right

      if (drag.mode === 'schedule') {
        // Only draws a landing pad while the pointer is actually over the timeline.
        setGhostValue(inside ? { start_min: snap(yMin), duration_min: drag.duration } : null)
      } else if (drag.mode === 'resize') {
        const stop = Math.min(Math.max(snap(yMin), drag.start_min + SNAP_MIN), DAY_MIN)
        setGhostValue({ start_min: drag.start_min, duration_min: stop - drag.start_min })
      } else {
        const max = DAY_MIN - drag.duration
        const start = Math.max(0, Math.min(max, snap(yMin - drag.grabOffset)))
        setGhostValue({ start_min: start, duration_min: drag.duration })
      }
    }

    const finish = async () => {
      const g = ghostRef.current
      const d = drag
      const moved = movedRef.current
      setDrag(null)
      setGhostValue(null)
      if (!g || !moved) return // a plain click selects, it does not reschedule
      try {
        if (d.mode === 'schedule') {
          await api.patch(d.id, { day, start_min: g.start_min, duration_min: g.duration_min })
        } else {
          await api.patch(d.id, { start_min: g.start_min, duration_min: g.duration_min })
        }
        await load()
      } catch (e) {
        setError(e.message)
      }
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
    }
  }, [drag, day, load])

  // ---- actions ----

  const capture = async (e) => {
    e.preventDefault()
    const title = draft.trim()
    if (!title) return
    setDraft('')
    try {
      await api.create({ title })
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const scheduleAt = async (e) => {
    if (e.target.closest('.block')) return // double-clicking a block is not a create
    const rect = contentRef.current.getBoundingClientRect()
    const start = snap(((e.clientY - rect.top) / HOUR_PX) * 60)
    try {
      await api.create({ title: 'New block', day, start_min: start, duration_min: 30 })
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const selected = useMemo(
    () => [...blocks, ...inbox].find((b) => b.id === selectedId) || null,
    [blocks, inbox, selectedId],
  )

  const change = async (changes) => {
    try {
      await api.patch(selectedId, changes)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const remove = async () => {
    try {
      await api.remove(selectedId)
      setSelectedId(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const scheduledMin = blocks.reduce((n, b) => n + b.duration_min, 0)

  return (
    <div className={`layout ${selected ? 'with-editor' : ''}`}>
      <aside className="side">
        <h1 className="brand">sundial</h1>

        <form onSubmit={capture} className="capture">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Dump it here, press Enter"
            aria-label="Capture a task"
          />
        </form>

        <div className="side-head">
          Inbox {inbox.length > 0 && <span className="count">{inbox.length}</span>}
        </div>

        <ul className="inbox">
          {inbox.length === 0 && <li className="empty">Nothing waiting. Everything has a time.</li>}
          {inbox.map((b) => (
            <li
              key={b.id}
              className={`chip c-${b.color} ${selectedId === b.id ? 'sel' : ''}`}
              onPointerDown={(e) => beginDrag(e, 'schedule', b)}
              onClick={() => setSelectedId(b.id)}
            >
              <span className="chip-title">{b.title}</span>
              <span className="chip-dur">{durText(b.duration_min)}</span>
            </li>
          ))}
        </ul>

        {inbox.length > 0 && <p className="hint">Drag onto the timeline to give it a time.</p>}
      </aside>

      <main className="day">
        <header className="day-head">
          <button onClick={() => setDay(shiftDay(day, -1))} title="Previous day" aria-label="Previous day">‹</button>
          <button className="day-label" onClick={() => setDay(today)} title="Jump to today">
            {dayLabel(day, today)}
          </button>
          <button onClick={() => setDay(shiftDay(day, 1))} title="Next day" aria-label="Next day">›</button>
          <input
            type="date"
            value={day}
            onChange={(e) => e.target.value && setDay(e.target.value)}
            aria-label="Pick a date"
          />
          <span className="tally">
            {durText(scheduledMin)} planned · {durText(Math.max(DAY_MIN - scheduledMin, 0))} open
          </span>
          {error && <span className="error" title={error}>API error</span>}
        </header>

        <div className="scroller" ref={scrollerRef}>
          <div className="content" ref={contentRef} onDoubleClick={scheduleAt} title="Double-click to add a block">
            {HOURS.map((h) => (
              <div key={h} className="hour" style={{ top: h * HOUR_PX }}>
                <span className="hour-label">{hhmm(h * 60)}</span>
              </div>
            ))}

            {day === today && (
              <div className="now" style={{ top: (nowMin / 60) * HOUR_PX }}>
                <span className="now-dot" />
              </div>
            )}

            {blocks.map((b) => {
              const live = drag?.id === b.id && drag.mode !== 'schedule' && ghost
              const view = live ? ghost : b
              const isNow = day === today && b.start_min <= nowMin && nowMin < b.start_min + b.duration_min
              return (
                <div
                  key={b.id}
                  className={`block c-${b.color}${b.done ? ' done' : ''}${isNow ? ' current' : ''}${selectedId === b.id ? ' sel' : ''}`}
                  style={{ top: (view.start_min / 60) * HOUR_PX, height: Math.max((view.duration_min / 60) * HOUR_PX, 20) }}
                  onPointerDown={(e) => beginDrag(e, 'move', b)}
                  onClick={() => setSelectedId(b.id)}
                >
                  <span className="block-time">
                    {hhmm(view.start_min)}–{hhmm(view.start_min + view.duration_min)}
                  </span>
                  <span className="block-title">{b.title}</span>
                  <span
                    className="resize"
                    onPointerDown={(e) => beginDrag(e, 'resize', b)}
                    title="Drag to change length"
                  />
                </div>
              )
            })}

            {drag?.mode === 'schedule' && ghost && (
              <div
                className="block ghost"
                style={{ top: (ghost.start_min / 60) * HOUR_PX, height: (ghost.duration_min / 60) * HOUR_PX }}
              >
                <span className="block-time">{hhmm(ghost.start_min)}</span>
                <span className="block-title">{drag.title}</span>
              </div>
            )}
          </div>
        </div>
      </main>

      {selected && (
        <aside className="editor">
          <div className="editor-head">
            <input
              className="title-input"
              value={selected.title}
              onChange={(e) => change({ title: e.target.value || 'Untitled' })}
              aria-label="Title"
            />
            <button className="close" onClick={() => setSelectedId(null)} aria-label="Close editor">×</button>
          </div>

          <label className="field">
            <span>Length</span>
            <div className="dur-row">
              <input
                type="range" min="5" max="480" step="5"
                value={selected.duration_min}
                onChange={(e) => change({ duration_min: Number(e.target.value) })}
              />
              <b>{durText(selected.duration_min)}</b>
            </div>
          </label>

          <label className="field">
            <span>Colour</span>
            <div className="swatches">
              {COLORS.map((c) => (
                <button
                  key={c}
                  className={`swatch c-${c} ${selected.color === c ? 'on' : ''}`}
                  onClick={() => change({ color: c })}
                  aria-label={c}
                />
              ))}
            </div>
          </label>

          <label className="field">
            <span>Notes</span>
            <textarea
              rows="4"
              value={selected.notes}
              onChange={(e) => change({ notes: e.target.value })}
            />
          </label>

          <div className="editor-actions">
            {selected.day === null ? (
              <span className="muted">In the inbox — drag it onto the timeline.</span>
            ) : (
              <button onClick={() => change({ unschedule: true })}>Back to inbox</button>
            )}
            <button className={selected.done ? 'primary' : ''} onClick={() => change({ done: !selected.done })}>
              {selected.done ? 'Done' : 'Mark done'}
            </button>
            <button className="danger" onClick={remove}>Delete</button>
          </div>
        </aside>
      )}
    </div>
  )
}
