import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, durText, shiftDay,
} from './time'
import { bucketOf } from './agenda'
import { applyTheme, initialTheme, rememberTheme } from './theme'
import { createLatest, createWriteQueue } from './saving'
import Header from './components/Header'
import Inbox from './components/Inbox'
import Timeline from './components/Timeline'
import Editor from './components/Editor'
import Agenda from './components/Agenda'
import TabBar from './components/TabBar'

const VIEW_KEY = 'sundial-view'
// Where a new task lands in a section that has nothing in it yet.
const SECTION_START = { morning: 8 * 60, afternoon: 13 * 60, evening: 18 * 60 }

export default function App() {
  const [view, setView] = useState(() =>
    localStorage.getItem(VIEW_KEY) === 'calendar' ? 'calendar' : 'todo',
  )
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
  const captureRef = useRef(null)
  const ghostRef = useRef(null) // mirrors `ghost` so pointerup reads the live value
  const movedRef = useRef(false)
  const writes = useRef(createWriteQueue())
  const dayLoad = useRef(createLatest())
  const weekLoad = useRef(createLatest())
  const inFlight = useRef(null)

  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => { localStorage.setItem(VIEW_KEY, view) }, [view])

  const load = useCallback(async () => {
    // A request already on its way is for a day you have left. Drop it rather than let
    // it land later and paint that day's blocks under this day's heading.
    if (inFlight.current) inFlight.current.abort()
    const control = new AbortController()
    inFlight.current = control
    const wanted = day
    const ticket = dayLoad.current.begin()

    try {
      const data = await api.day(wanted, control.signal)
      if (dayLoad.current.isCurrent(ticket) && data.day === wanted) {
        setBlocks(data.blocks)
        setInbox(data.inbox)
        setToday(data.today)
        setError('')
      }
    } catch (e) {
      if (e.name !== 'AbortError' && dayLoad.current.isCurrent(ticket)) setError(e.message)
    }

    const weekTicket = weekLoad.current.begin()
    try {
      const wk = await api.week(wanted, 7, control.signal)
      if (weekLoad.current.isCurrent(weekTicket)) setWeek(wk.days)
    } catch {
      // the week strip is decoration; a failure there must not blank the day
    }
  }, [day])

  useEffect(() => { load() }, [load])

  /** Writes for one block go out one at a time, in the order they were asked for.
   *
   * Without this, two keystrokes are two requests racing each other and the reply to
   * the first one lands last, putting the older text back. The day is read back after
   * the write, and a rejection is handed to whoever asked, so the editor can say so.
   */
  const write = useCallback(
    async (id, changes) => {
      const saved = await writes.current.run(id, () => api.patch(id, changes))
      await load()
      return saved
    },
    [load],
  )

  useEffect(() => {
    const t = setInterval(() => setNowMin(minsNow()), 30_000)
    return () => clearInterval(t)
  }, [])

  // Land somewhere useful: half an hour before now, else 7am.
  useEffect(() => {
    if (!scrollerRef.current) return
    const focusMin = day === todayISO() ? nowMin - 30 : 7 * 60
    scrollerRef.current.scrollTop = Math.max(0, (focusMin / 60) * HOUR_PX - 60)
  }, [day, view]) // eslint-disable-line react-hooks/exhaustive-deps

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
          await write(d.id, { day, start_min: g.start_min, duration_min: g.duration_min })
        } else {
          await write(d.id, { start_min: g.start_min, duration_min: g.duration_min })
        }
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
    try {
      await api.create({ title })
      setDraft('') // only once it exists: a failure must not eat what was typed
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  /** Adding to a section drops the task after whatever is already there, rather
   *  than on top of it. "Anytime" means the inbox. */
  const addToSection = async (key) => {
    const body = { title: 'New task', duration_min: 30 }
    if (key !== 'anytime') {
      const inSection = blocks
        .filter((b) => bucketOf(b.start_min) === key)
        .sort((a, b) => a.start_min - b.start_min)
      const last = inSection[inSection.length - 1]
      const start = last
        ? last.start_min + last.duration_min + SNAP_MIN
        : SECTION_START[key] ?? 9 * 60
      body.day = day
      body.start_min = snap(Math.min(start, DAY_MIN - 30))
    }
    try {
      const created = await api.create(body)
      await load()
      setSelectedId(created.id)
    } catch (err) {
      setError(err.message)
    }
  }

  const scheduleAt = async (e) => {
    if (e.target.closest('.block')) return // double-clicking a block is not a create
    const rect = contentRef.current.getBoundingClientRect()
    const start = snap(((e.clientY - rect.top) / HOUR_PX) * 60)
    // Near midnight there is no room for half an hour: take what fits rather
    // than asking the API for a block that runs off the end of the day.
    const duration = Math.max(SNAP_MIN, Math.min(30, DAY_MIN - start))
    try {
      await api.create({ title: 'New block', day, start_min: start, duration_min: duration })
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const selected = useMemo(
    () => [...blocks, ...inbox].find((b) => b.id === selectedId) || null,
    [blocks, inbox, selectedId],
  )

  const toggleDone = async (block) => {
    try {
      await write(block.id, { done: !block.done })
    } catch (e) {
      setError(e.message)
    }
  }

  const remove = async () => {
    const id = selectedId
    try {
      // Through the queue, so a write still in flight for this block cannot land after
      // the delete and leave a row that was meant to be gone.
      await writes.current.run(id, () => api.remove(id))
      setSelectedId(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const planned = blocks.reduce((n, b) => n + b.duration_min, 0)
  const layout = ['layout']
  if (view === 'calendar') layout.push('with-rail')
  if (selected) layout.push('with-editor')

  return (
    <div className={layout.join(' ')}>
      {view === 'calendar' && (
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
      )}

      <main className="day">
        <Header
          day={day}
          today={today}
          tally={`${durText(planned)} planned · ${durText(Math.max(DAY_MIN - planned, 0))} open`}
          week={week}
          theme={theme}
          error={error}
          onPickDay={setDay}
          onShift={(delta) => setDay(shiftDay(day, delta))}
          onTheme={toggleTheme}
        />

        {view === 'todo' ? (
          <div className="view">
            <Agenda
              blocks={blocks}
              inbox={inbox}
              draft={draft}
              captureRef={captureRef}
              onDraft={setDraft}
              onCapture={capture}
              onOpen={setSelectedId}
              onToggle={toggleDone}
              onAddAt={addToSection}
            />
          </div>
        ) : (
          <div className="view is-timeline">
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
          </div>
        )}
      </main>

      {selected && (
        <Editor
          key={selected.id}
          block={selected}
          today={today}
          onSave={write}
          onRemove={remove}
          onClose={() => setSelectedId(null)}
        />
      )}

      <TabBar view={view} onPick={setView} />
    </div>
  )
}
