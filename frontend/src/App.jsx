import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import {
  HOUR_PX, SNAP_MIN, DAY_MIN, todayISO, minsNow, snap, durText, shiftDay, busyMinutes, hhmm,
  appointments,
} from './time'
import { bucketOf } from './agenda'
import { applyTheme, initialTheme, rememberTheme } from './theme'
import { dayIsClear } from './art'
import { syncNote } from './calendar'
import { createLatest, createWriteQueue } from './saving'
import Header from './components/Header'
import Inbox from './components/Inbox'
import Timeline from './components/Timeline'
import Editor from './components/Editor'
import Agenda from './components/Agenda'
import CalendarPanel from './components/CalendarPanel'

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
  // A finished task fills its box at once and leaves the list a beat later, so the tap has a
  // result before the network does anything. Both lists are local state: a reload landing
  // mid-animation cannot cut the motion short.
  const [leaving, setLeaving] = useState([])
  const [settling, setSettling] = useState([])
  // The calendar is context layered beside the plan, so it keeps its own state: a calendar
  // that will not load must leave the day exactly as it was.
  const [calendar, setCalendar] = useState(null)
  const [calendarDay, setCalendarDay] = useState({ day: null, events: [] })
  const [syncing, setSyncing] = useState(false)
  const [calendarNote, setCalendarNote] = useState('')
  const [connecting, setConnecting] = useState(false)
  const timers = useRef([])

  const contentRef = useRef(null)
  const scrollerRef = useRef(null)
  const captureRef = useRef(null)
  const ghostRef = useRef(null) // mirrors `ghost` so pointerup reads the live value
  const movedRef = useRef(false)
  const writes = useRef(createWriteQueue())
  const dayLoad = useRef(createLatest())
  const weekLoad = useRef(createLatest())
  const calendarLoad = useRef(createLatest())
  const askedToSync = useRef(false)
  const inFlight = useRef(null)

  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => () => timers.current.forEach(window.clearTimeout), [])
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

  const loadCalendar = useCallback(async (which) => {
    const ticket = calendarLoad.current.begin()
    try {
      const [status, day] = await Promise.all([api.calendars(), api.events(which)])
      if (!calendarLoad.current.isCurrent(ticket)) return
      setCalendar(status)
      setCalendarDay(day)
    } catch {
      // Context, not the plan: a calendar that will not read is not an error worth the
      // header. The panel says "not connected" or keeps the last good answer.
    }
  }, [])

  const runSync = useCallback(
    async (ifStaleSeconds = 0) => {
      setSyncing(true)
      try {
        const result = await api.syncCalendars(ifStaleSeconds)
        setCalendarNote(syncNote(result))
        await loadCalendar(day)
      } catch (e) {
        setCalendarNote(e.message)
      } finally {
        setSyncing(false)
      }
    },
    [day, loadCalendar],
  )

  useEffect(() => {
    if (view !== 'calendar') return
    loadCalendar(day)
  }, [view, day, loadCalendar])

  /** Opening the calendar view is the schedule. The server decides whether that means going
   *  to iCloud, so switching views never hammers it, and nothing runs in the background
   *  while the app is shut — a choice, explained in docs/calendar-sync.md.
   *
   *  Waits for the status before asking: syncing with nothing to sync with produces a
   *  refusal, and the rail would carry a filesystem path where a sentence belongs. */
  useEffect(() => {
    if (view !== 'calendar' || !calendar?.configured || askedToSync.current) return
    askedToSync.current = true
    runSync(900)
  }, [view, calendar, runSync])

  /** Typing a credential into the panel: the only secret this app is ever given.

   *  It goes straight to the server that writes the file, and the reply is the provider's
   *  state rather than an echo. Then it syncs — "is that password right?" is the only question
   *  anybody has at that moment, and nothing else can answer it. Returns a sentence when it
   *  did not work, so the panel can put it beside the fields.
   */
  const connectCalendar = useCallback(
    async (provider, fields) => {
      setConnecting(true)
      try {
        const state = await api.saveCredentials(provider, fields)
        setCalendarNote(state.why || 'Connected. Reading the calendar…')
        await loadCalendar(day)
        // The auto-sync below only ever runs once; connecting is a second reason to ask.
        // Deliberately not awaited: whether iCloud accepts the password is the sync's answer,
        // and the form should not sit there spinning while a server thinks about it.
        askedToSync.current = true
        runSync()
        return ''
      } catch (e) {
        return e.message
      } finally {
        setConnecting(false)
      }
    },
    [day, loadCalendar, runSync],
  )

  const toggleCalendar = useCallback(
    async (ref, enabled) => {
      try {
        await api.setCalendar(ref, enabled)
        await loadCalendar(day)
      } catch (e) {
        setCalendarNote(e.message)
      }
    },
    [day, loadCalendar],
  )

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
        if (!inside) {
          // Only draws a landing pad while the pointer is actually over the timeline.
          setGhostValue(null)
          return
        }
        // An item dropped near midnight takes the latest position it fits in, instead
        // of showing a landing pad that the API is going to refuse.
        const last = Math.max(0, DAY_MIN - drag.duration)
        setGhostValue({ start_min: Math.min(snap(yMin), last), duration_min: drag.duration })
      } else if (drag.mode === 'resize') {
        const stop = Math.min(Math.max(snap(yMin), drag.start_min + SNAP_MIN), DAY_MIN)
        setGhostValue({ start_min: drag.start_min, duration_min: stop - drag.start_min })
      } else {
        const max = DAY_MIN - drag.duration
        const start = Math.max(0, Math.min(max, snap(yMin - drag.grabOffset)))
        setGhostValue({ start_min: start, duration_min: drag.duration })
      }
    }

    const commit = async () => {
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

    // A cancelled gesture is not a drag that finished: the browser took the pointer
    // away (a system gesture, a phone call), so nothing was decided and nothing is
    // written. Treating it as a drop is how a block moved without being asked to.
    const abandon = () => {
      setDrag(null)
      setGhostValue(null)
      movedRef.current = false
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', abandon)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', abandon)
    }
  }, [drag, day, write])

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

  /** The one place a row's data is changed locally, so the optimistic state cannot disagree
   *  with itself when the task lives in the inbox rather than the day. */
  const patchLocal = (id, changes) => {
    const apply = (list) => list.map((b) => (b.id === id ? { ...b, ...changes } : b))
    setBlocks(apply)
    setInbox(apply)
  }

  /** Fill, hold while you read it, then leave. The hold is the whole difference between a
   *  considered interface and an abrupt one: move it too fast and you never see what you
   *  checked. Under reduce-motion the row still fills and still ends up in the finished list —
   *  it just gets there without travelling. */
  const depart = (id) => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const hold = still ? 0 : 520
    const travel = still ? 0 : 260
    timers.current.push(
      window.setTimeout(() => {
        setLeaving((ids) => (ids.includes(id) ? ids : [...ids, id]))
        timers.current.push(
          window.setTimeout(() => {
            setLeaving((ids) => ids.filter((x) => x !== id))
            setSettling((ids) => [...ids, id])
            timers.current.push(
              window.setTimeout(() => setSettling((ids) => ids.filter((x) => x !== id)), 460),
            )
          }, travel),
        )
      }, hold),
    )
  }

  const toggleDone = async (block) => {
    const on = !block.done
    patchLocal(block.id, { done: on })
    if (on) depart(block.id)
    try {
      await write(block.id, { done: on })
    } catch (e) {
      // It never happened: put the row back where it was, and stop it leaving.
      setError(e.message)
      patchLocal(block.id, { done: !on })
      setLeaving((ids) => ids.filter((x) => x !== block.id))
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

  // The calendar's own events, placed on the clock, and the blocks that have to make room for
  // them. Only for the day on screen: the panel's events belong to whichever day it last
  // fetched, and drawing yesterday's appointments onto today would be a quiet lie.
  const calendarColour = useMemo(
    () => Object.fromEntries((calendar?.calendars ?? []).map((c) => [c.ref, c.colour])),
    [calendar],
  )
  const calendarName = useMemo(
    () => Object.fromEntries((calendar?.calendars ?? []).map((c) => [c.ref, c.name])),
    [calendar],
  )
  const calendarInDay = useMemo(
    () => appointments(blocks, calendarDay.day === day ? calendarDay.events : [], day),
    [blocks, calendarDay, day],
  )

  // Time spoken for, not the sum of the durations: a block nested inside another is
  // not two hours of your day, and "open" has to mean open.
  const planned = busyMinutes(blocks)
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
          <CalendarPanel
            status={calendar}
            events={calendarDay.events}
            busy={syncing}
            note={calendarNote}
            onSync={runSync}
            onToggle={toggleCalendar}
            onConnect={connectCalendar}
            connecting={connecting}
          />
        </aside>
      )}

      <main className="day">
        <Header
          day={day}
          today={today}
          clock={hhmm(nowMin)}
          tally={`${durText(planned)} planned · ${durText(Math.max(DAY_MIN - planned, 0))} open`}
          view={view}
          theme={theme}
          error={error}
          onPickDay={setDay}
          onShift={(delta) => setDay(shiftDay(day, delta))}
          onView={setView}
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
              leaving={leaving}
              settling={settling}
              dayClear={dayIsClear(blocks, inbox, day, today)}
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
              appointments={calendarInDay.spans}
              squeezed={calendarInDay.squeezed}
              colourOf={calendarColour}
              nameOf={calendarName}
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
          day={day}
          onSave={write}
          onRemove={remove}
          onClose={() => setSelectedId(null)}
        />
      )}

    </div>
  )
}
