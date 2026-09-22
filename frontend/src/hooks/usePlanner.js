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
import { describeApply, payloadItems } from '../templates'
import {
  ROLLOVER_DEFAULT, dismissed, leaveThere, rolloverAction, stillWaiting,
} from '../rollover'
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
  // The templates, and what the last apply did. The note is not a status flag and never expires
  // on a timer: it says what happened, and the next thing you do replaces it.
  const [templates, setTemplates] = useState([])
  const [templateNote, setTemplateNote] = useState('')
  // Yesterday's unfinished work, as the server reports it — only ever non-empty for today — and
  // the ids this tab has already left alone. The setting that decides what happens to either is a
  // row in the database, so it is read with the day rather than remembered here.
  const [leftover, setLeftover] = useState([])
  const [gone, setGone] = useState(() => dismissed(todayISO()))
  const [rollover, setRolloverSetting] = useState(ROLLOVER_DEFAULT)
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
        setLeftover(data.leftover ?? [])
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

    // The templates, for the panel and for the apply control in Today. Same reasoning as the
    // rules: nothing about the day that is already drawn depends on them arriving.
    try {
      const stored = await api.templates(control.signal)
      if (dayLoad.current.isCurrent(ticket)) setTemplates(stored.templates)
    } catch {
      // as above
    }

    // The app's settings, for the rollover decision. A failure here is the least harmful one in
    // this function: what is left behind is the default, and the default is the answer that
    // touches nothing until somebody taps.
    try {
      const stored = await api.settings(control.signal)
      if (dayLoad.current.isCurrent(ticket)) setRolloverSetting(stored.rollover)
    } catch {
      // as above
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

  /** What is left from yesterday, less what this tab has already left alone.
   *
   *  The setting decides whether any of it is drawn at all: "ask" shows the section, "leave" says
   *  nothing about any of it, and "anytime" moves it — by itself, just below — so by the time the
   *  page settles there is nothing left to show. Only one of the three ever writes to a day you
   *  have already had, and it is the one you chose.
   */
  const offered = useMemo(
    () => (rolloverAction(rollover, leftover) === 'ask' ? stillWaiting(leftover, gone) : []),
    [rollover, leftover, gone],
  )

  // What this tab has left alone belongs to a day rather than to the tab. A session that stays
  // open past midnight gets a new `today` from the server, and yesterday's "not now" must not
  // follow it: a block still sitting there on the new day is one nobody has dealt with.
  useEffect(() => setGone(dismissed(today)), [today])

  /** The one thing on this page that happens without being tapped.
   *
   *  "Move to Anytime automatically" means exactly that: the first time today is looked at, the
   *  unfinished blocks of yesterday go back to Anytime. Once per client day, because a write that
   *  failed would otherwise be retried on every load for the rest of the afternoon — and because
   *  moving them is what stops them qualifying, so a second pass would find nothing to do anyway.
   */
  const settled = useRef(null)
  useEffect(() => {
    if (rolloverAction(rollover, leftover) !== 'move' || settled.current === today) return
    settled.current = today
    ;(async () => {
      try {
        for (const block of leftover) {
          await writes.current.run(block.id, () => api.patch(block.id, { unschedule: true }))
        }
        await load()
      } catch (err) {
        setError(err.message)
      }
    })()
  }, [rollover, leftover, today, load])

  /** Move one of yesterday's onto today, or back to Anytime.
   *
   *  Both are the ordinary re-day write, which is the whole reason none of this needed a table or a
   *  marker: a block's day is where it is, so moving it is the record. The block keeps its hour
   *  when it moves to Today, because that is the time it was already planned for. It does leave
   *  yesterday — the section says so before you tap, and "leave there" is how you keep it there.
   */
  const moveLeftover = async (block, where) => {
    const changes =
      where === 'anytime' ? { unschedule: true } : { day: today, start_min: block.start_min }
    try {
      await writes.current.run(block.id, () => api.patch(block.id, changes))
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  /** Leave one where it is, for the rest of this tab's day. Nothing is written: the block is
   *  already on the day it was, and not asking again is the whole of the answer. */
  const leaveOne = (block) => setGone(leaveThere(today, block.id))

  /** Change the setting. Optimistic, like a row being ticked: the choice should land under the
   *  finger, and a refusal has to put the other one back rather than leave the panel saying
   *  something the server did not store. */
  const setRollover = async (value) => {
    const before = rollover
    setRolloverSetting(value)
    try {
      const saved = await api.patchSettings({ rollover: value })
      setRolloverSetting(saved.rollover)
    } catch (err) {
      setRolloverSetting(before)
      setError(err.message)
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

  /** A template's contents, saved as one list.
   *
   *  Keyed through the write queue on the template's id, like a routine's fields: two edits in
   *  quick succession are two writes of the whole list, and the second one must not be overtaken
   *  by the first. The reply is not applied locally — the queue's ordering is what makes the
   *  last write the one that stands, and a reload after it is what puts the server's order back
   *  on the screen.
   */
  const saveTemplateItems = async (id, items) => {
    await writes.current.run(id, () => api.putTemplateItems(id, payloadItems(items)))
    await load()
  }

  /** Everything about a template except its contents, which have their own path above.
   *
   *  Handed to the panel as one object rather than as six props: the panel does not need to know
   *  which of these goes to which route, and the list is long enough that six props would be
   *  six chances to pass the wrong one.
   */
  const templateActions = {
    async create(name) {
      try {
        const made = await api.createTemplate({ name })
        setTemplateNote(`${made.name} is ready to fill in.`)
        await load()
      } catch (err) {
        setError(err.message)
      }
    },
    async rename(id, name) {
      try {
        await api.renameTemplate(id, name)
        await load()
      } catch (err) {
        setError(err.message)
      }
    },
    async duplicate(id) {
      try {
        const copy = await api.duplicateTemplate(id)
        setTemplateNote(`${copy.name} is a copy of ${templates.find((t) => t.id === id)?.name}.`)
        await load()
      } catch (err) {
        setError(err.message)
      }
    },
    async remove(id) {
      try {
        await writes.current.run(id, () => api.removeTemplate(id))
        await load()
      } catch (err) {
        setError(err.message)
      }
    },
    async saveItems(id, items) {
      try {
        await saveTemplateItems(id, items)
      } catch (err) {
        setError(err.message)
      }
    },
    /** Put a template on a day, and say what that added.
     *
     *  The day is handed in rather than read from the screen: the panel under You always applies
     *  to today and says so on the button, and the control in Today applies to the day being
     *  looked at. Neither of those is a guess this function should be making.
     *
     *  Additive on purpose: this reads nothing, moves nothing and replaces nothing, so a day
     *  that already has a plan on it keeps the plan. An apply that lands twice is two of
     *  everything, which is the honest answer — there is no "already applied" to notice.
     */
    async apply(id, on) {
      try {
        const result = await api.applyTemplate(id, on ?? day)
        setTemplateNote(describeApply(result))
        await load()
      } catch (err) {
        setError(err.message)
      }
    },
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
    // `leftover` here is what the section draws rather than the raw list: the setting and this
    // tab's "leave there" have both had their say by the time it arrives.
    leftover: offered, rollover, setRollover, moveLeftover, leaveOne,
    templates, templateNote, templateActions,
    load, write, capture, addToSection, scheduleAt, toggleDone, remove, saveRoutine, editor,
  }
}
