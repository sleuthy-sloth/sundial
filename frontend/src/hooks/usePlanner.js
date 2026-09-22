/** The day's own state: what is planned, what is still in the inbox, and every write that
 *  changes either.
 *
 * Lifted out of App.jsx, which had become the place where the planner's rules, the
 * calendar's and the pointer's all met. Nothing here knows what the screen looks like: it
 * hands back the day and the actions that change it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { DAY_MIN, HOUR_PX, SNAP_MIN, snap, todayISO } from '../time'
import { bucketOf } from '../agenda'
import { createLatest, createWriteQueue } from '../saving'

/** Where a new task lands in a section that has nothing in it yet. */
const SECTION_START = { morning: 8 * 60, afternoon: 13 * 60, evening: 18 * 60 }

export function usePlanner({ contentRef }) {
  const [day, setDay] = useState(todayISO)
  const [today, setToday] = useState(todayISO)
  const [blocks, setBlocks] = useState([])
  const [inbox, setInbox] = useState([])
  // Read on every load, and drawn by nothing yet: the week the day sits in is already being
  // fetched, and the screen that shows it is not here.
  const [week, setWeek] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  // A finished task fills its box at once and leaves the list a beat later, so the tap has a
  // result before the network does anything. Both lists are local state: a reload landing
  // mid-animation cannot cut the motion short.
  const [leaving, setLeaving] = useState([])
  const [settling, setSettling] = useState([])

  const timers = useRef([])
  const writes = useRef(createWriteQueue())
  const dayLoad = useRef(createLatest())
  const weekLoad = useRef(createLatest())
  const inFlight = useRef(null)

  useEffect(() => () => timers.current.forEach(window.clearTimeout), [])

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

  return {
    day, setDay, today, blocks, inbox, week,
    selectedId, setSelectedId, selected,
    draft, setDraft, error, setError,
    leaving, settling,
    load, write, capture, addToSection, scheduleAt, toggleDone, remove,
  }
}
