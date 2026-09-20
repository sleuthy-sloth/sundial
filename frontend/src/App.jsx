import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, durText, shiftDay, dayLabel,
} from './time'
import { applyTheme, initialTheme, rememberTheme } from './theme'
import Header from './components/Header'
import Inbox from './components/Inbox'
import Timeline from './components/Timeline'
import Editor from './components/Editor'

export default function App() {
  const [day, setDay] = useState(todayISO())
  const [today, setToday] = useState(todayISO())
  const [blocks, setBlocks] = useState([])
  const [inbox, setInbox] = useState([])
  const [week, setWeek] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [nowMin, setNowMin] = useState(minsNow())
  const [drag, setDrag] = useState(null)
  const [ghost, setGhost] = useState(null)
  const [theme, setTheme] = useState(initialTheme)

  const contentRef = useRef(null)
  const scrollerRef = useRef(null)
  const ghostRef = useRef(null) // mirrors `ghost` so pointerup reads the live value
  const movedRef = useRef(false)

  useEffect(() => { applyTheme(theme) }, [theme])

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
    try {
      const wk = await api.week(day)
      setWeek(wk.days)
    } catch {
      // the week strip is decoration; a failure there must not blank the day
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

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    rememberTheme(next)
    setTheme(next)
  }

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

  const planned = blocks.reduce((n, b) => n + b.duration_min, 0)

  return (
    <div className={`layout${selected ? ' with-editor' : ''}`}>
      <aside className="side">
        <h1 className="brand">sundial</h1>
        <Inbox
          items={inbox}
          draft={draft}
          selectedId={selectedId}
          onDraft={setDraft}
          onCapture={capture}
          onPointerDown={beginDrag}
          onSelect={setSelectedId}
        />
      </aside>

      <main className="day">
        <Header
          day={day}
          today={today}
          dayName={dayLabel(day, today)}
          tally={`${durText(planned)} planned · ${durText(Math.max(DAY_MIN - planned, 0))} open`}
          week={week}
          theme={theme}
          error={error}
          onPickDay={setDay}
          onShift={(delta) => setDay(shiftDay(day, delta))}
          onTheme={toggleTheme}
        />
        <Timeline
          day={day}
          today={today}
          blocks={blocks}
          nowMin={nowMin}
          selectedId={selectedId}
          drag={drag}
          ghost={ghost}
          contentRef={contentRef}
          scrollerRef={scrollerRef}
          onDoubleClick={scheduleAt}
          onPointerDown={beginDrag}
          onSelect={setSelectedId}
        />
      </main>

      {selected && (
        <Editor
          block={selected}
          onChange={change}
          onRemove={remove}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}
