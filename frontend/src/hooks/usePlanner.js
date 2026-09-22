/** The day's own state: what is planned, what is still in the inbox, and every write that
 *  changes either.
 *
 * Lifted out of App.jsx, which had become the place where the planner's rules, the
 * calendar's and the pointer's all met. Nothing here knows what the screen looks like: it
 * hands back the day and the actions that change it.
 *
 * Routines join the day rather than sitting beside it. An occurrence arrives from `/api/day` in
 * the same list as the blocks, and the one thing this module has to know about it is where a
 * write goes: an occurrence has no row, so a change to one is a change to its rule's day. That
 * decision is made in `send`, once, and every write path here goes through it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { DAY_MIN, HOUR_PX, SNAP_MIN, snap, todayISO } from '../time'
import { bucketOf } from '../agenda'
import { isOccurrence, occurrenceOf } from '../routines'
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
  // The rules themselves, which the day view does not need and the editor does: an occurrence
  // knows which routine it belongs to, and the panel is where that routine is read and changed.
  const [routines, setRoutines] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [routineId, setRoutineId] = useState(null)
  // Which half of a routine's day the panel is showing: the rule, or one day of it. Only ever
  // 'routine' for a subject that has a rule behind it.
  const [half, setHalf] = useState('day')
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
  // What the lists hold right now, for the write path: a drag hands over an id, and the
  // decision about whether that id is a block or a day of a routine needs the row, not a guess.
  const live = useRef([])
  live.current = [...blocks, ...inbox]

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

    // The rules, for the panel. A failure here must not blank the day: the occurrences are
    // already in it, and the only thing lost is the ability to open the rule behind one.
    try {
      const rules = await api.routines(control.signal)
      if (dayLoad.current.isCurrent(ticket)) setRoutines(rules.routines)
    } catch {
      // leave whatever was there
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

  /** Where a write for this row goes.
   *
   * An occurrence is a day of a rule: it has no row, so the request names the routine and the
   * date, and the server writes the one override that says this day differs. Everything else is
   * a block and is addressed as one. A day and a "back to anytime" sent for an occurrence are
   * dropped rather than forwarded — an occurrence is always at its hour, and the panel does not
   * offer either control for one.
   */
  const send = useCallback((block, changes) => {
    const { routine_id, day: on } = occurrenceOf(block)
    if (!routine_id) return api.patch(block.id, changes)
    const { day: _day, unschedule: _unschedule, ...rest } = changes
    return api.patchOccurrence(routine_id, on, rest)
  }, [])

  /** Writes for one block go out one at a time, in the order they were asked for.
   *
   * Without this, two keystrokes are two requests racing each other and the reply to
   * the first one lands last, putting the older text back. The day is read back after
   * the write, and a rejection is handed to whoever asked, so the editor can say so.
   */
  const saveBlock = useCallback(
    async (block, changes) => {
      const saved = await writes.current.run(block.id, () => send(block, changes))
      await load()
      return saved
    },
    [load, send],
  )

  /** The same, for a rule. Keyed by the routine's own id, so a rename and a colour change on
   *  the same routine cannot overtake each other. */
  const saveRoutine = useCallback(
    async (id, changes) => {
      const saved = await writes.current.run(id, () => api.patchRoutine(id, changes))
      await load()
      return saved
    },
    [load],
  )

  /** A drag knows the id of the row it moved and nothing else. */
  const write = useCallback(
    async (id, changes) => {
      const block = live.current.find((b) => b.id === id)
      if (block) return saveBlock(block, changes)
      const saved = await writes.current.run(id, () => api.patch(id, changes))
      await load()
      return saved
    },
    [load, saveBlock],
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

  /** The rule behind the day that is open, when the day that is open has one. */
  const owner = useMemo(
    () =>
      selected && isOccurrence(selected)
        ? routines.find((r) => r.id === selected.routine_id) || null
        : null,
    [selected, routines],
  )

  const selectedRoutine = useMemo(
    () => routines.find((r) => r.id === routineId) || null,
    [routines, routineId],
  )

  /** What the panel is about: one day, or one rule.
   *
   * One panel serves all three of "a block", "one day of a routine" and "the rule itself",
   * which is deliberate: the choice between editing a day and editing the routine is a choice
   * *within* a thing being edited, not a second thing to open. `block` is null when the rule was
   * opened from somewhere other than one of its own days, and then there is no day to go back to.
   */
  const subject = useMemo(() => {
    if (selected) {
      if (owner && half === 'routine') return { kind: 'routine', block: selected, routine: owner }
      return { kind: 'block', block: selected, routine: owner }
    }
    if (selectedRoutine) return { kind: 'routine', block: null, routine: selectedRoutine }
    return null
  }, [selected, owner, selectedRoutine, half])

  /** Open a day. Any rule that was being edited is put down: one panel, one subject. */
  const open = useCallback((id) => {
    setRoutineId(null)
    setHalf('day')
    setSelectedId(id)
  }, [])

  const openRoutine = useCallback((id) => {
    setSelectedId(null)
    setRoutineId(id)
  }, [])

  const close = useCallback(() => {
    setSelectedId(null)
    setRoutineId(null)
  }, [])

  /** Turn a block into a rule.
   *
   * The routine takes the block's fields and its day, and the block goes. Both halves are
   * needed: a routine starting today plus today's block would be the same hour twice, and a
   * routine starting tomorrow would leave today looking as though the repeat had not taken.
   */
  const makeRepeat = async (block, repeat) => {
    try {
      const routine = await api.createRoutine({
        title: block.title,
        start_min: block.start_min,
        duration_min: block.duration_min,
        color: block.color,
        icon: block.icon,
        notes: block.notes,
        start_date: block.day ?? day,
        ...repeat,
      })
      await writes.current.run(block.id, () => api.remove(block.id))
      setSelectedId(null)
      await load()
      openRoutine(routine.id)
    } catch (err) {
      setError(err.message)
    }
  }

  /** Take one day out of a rule. */
  const skipOccurrence = async (block) => {
    const { routine_id, day: on } = occurrenceOf(block)
    try {
      await writes.current.run(block.id, () => api.skipOccurrence(routine_id, on))
      close()
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  /** Put one day back to what the rule says. */
  const resetOccurrence = async (block) => {
    const { routine_id, day: on } = occurrenceOf(block)
    try {
      await writes.current.run(block.id, () => api.resetOccurrence(routine_id, on))
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

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
      close()
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  /** Delete a rule, and every day of it that had been changed. */
  const removeRoutine = async (id) => {
    try {
      await writes.current.run(id, () => api.removeRoutine(id))
      close()
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  /** The panel's one destructive button, whichever kind of thing it is about.
   *
   * A day of a routine is not deleted — deleting it would mean nothing, since the rule would
   * bring it back — so for one of those the button skips that day instead, and says so.
   */
  const removeSubject = async () => {
    if (subject?.kind === 'routine') return removeRoutine(subject.routine.id)
    if (subject?.block && isOccurrence(subject.block)) return skipOccurrence(subject.block)
    return remove()
  }

  /** What the editor panel is handed. One object, so the panel does not have to know which
   *  kind of thing it is saving: `onSave` goes to whichever half is on screen. */
  const editor = {
    onSave: (changes) =>
      subject?.kind === 'routine'
        ? saveRoutine(subject.routine.id, changes)
        : saveBlock(subject.block, changes),
    onRepeat: (repeat) => makeRepeat(subject.block, repeat),
    onSkip: () => skipOccurrence(subject.block),
    onReset: () => resetOccurrence(subject.block),
    onRemove: removeSubject,
    onHalf: setHalf,
  }

  return {
    day, setDay, today, blocks, inbox, week, routines,
    selectedId, selected, subject, open, openRoutine, close,
    draft, setDraft, error, setError,
    leaving, settling,
    load, write, capture, addToSection, scheduleAt, toggleDone, remove, saveRoutine, editor,
  }
}
