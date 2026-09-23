import { useCallback, useEffect, useRef, useState } from 'react'

import { ICONS } from '../icons'
import { stepsOf, whereSteps } from '../subtasks'
import { durText, hhmm } from '../time'
import {
  REPEATS,
  WEEKDAYS,
  WEEKDAY_LABELS,
  differsFromRoutine,
  everyWeeks,
  isOccurrence,
  isoWeekday,
  toggleWeekday,
  weekdaysFor,
} from '../routines'
import Glyph from './Glyph'

const COLORS = ['slate', 'sky', 'violet', 'amber', 'emerald', 'rose', 'teal', 'indigo']

// How long the typing has to stop before what was typed is sent.
const HOLD = 450

/** The checklist under the thing the panel has open.
 *
 *  Its own component because it keeps its own state: the name being typed into a step, and the
 *  name being typed into the box that adds one. Neither is a change to the block, so neither
 *  goes out with the title field's own debounce — a step's new name is sent when you leave it or
 *  press Enter, and a step is created when you ask for one.
 *
 *  No box on the rule half. The steps there are the definitions every day of the rule draws, and
 *  a tick is a fact about one morning: a checkbox on the rule would be a control that writes
 *  nothing. `where.tickable` is that decision, made once in `subtasks.js`.
 *
 *  The names are inputs rather than text, so a step is renamed where it was written. The list
 *  keeps the server's order — a reload after every write is what puts it back — and an empty
 *  checklist shows nothing but the box that starts one.
 */
function Steps({ lines, where, onAdd, onRename, onRemove, onTick }) {
  const [names, setNames] = useState({})
  const [fresh, setFresh] = useState('')

  const nameOf = (step) => names[step.id] ?? step.title

  const commit = (step) => {
    const name = nameOf(step).trim()
    setNames((held) => {
      const { [step.id]: _typed, ...rest } = held
      return rest
    })
    if (name && name !== step.title) onRename(step.id, name)
  }

  const create = (event) => {
    event.preventDefault()
    const name = fresh.trim()
    if (!name) return
    setFresh('')
    onAdd(name)
  }

  return (
    <div className="field field-steps">
      <span>Steps</span>

      {lines.length > 0 && (
        <ul className="step-list">
          {lines.map((step, index) => (
            <li className={step.done ? 'step-edit done' : 'step-edit'} key={step.id}>
              {where?.tickable && (
                <button
                  type="button"
                  className="step-notch"
                  role="checkbox"
                  aria-checked={step.done}
                  aria-label={
                    step.done ? `Mark ${step.title} not done` : `Mark ${step.title} done`
                  }
                  onClick={() => onTick(step.id, !step.done)}
                />
              )}
              <input
                className="step-name"
                value={nameOf(step)}
                onChange={(e) =>
                  setNames((held) => ({ ...held, [step.id]: e.target.value }))
                }
                onBlur={() => commit(step)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    commit(step)
                  }
                }}
                aria-label={`Step ${index + 1} name`}
              />
              <button
                type="button"
                className="step-remove"
                onClick={() => onRemove(step.id)}
                aria-label={`Remove step ${index + 1}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="step-add" onSubmit={create}>
        <input
          className="step-new"
          value={fresh}
          onChange={(e) => setFresh(e.target.value)}
          placeholder="Add a step"
          aria-label="Add a step"
        />
        <button type="submit">Add</button>
      </form>

      {where?.kind === 'occurrence' && (
        <span className="field-note">
          Steps belong to the routine: a new one is on every day of it, and a tick is about this
          day alone.
        </span>
      )}
    </div>
  )
}

/** The editor owns what is on screen while you type.
 *
 * The server's copy of a block arrives a round trip after each write, and a round trip
 * is exactly when the text you are still writing would be replaced by the text you
 * started from. So the fields keep their own draft: a pause sends it, leaving the field
 * sends it, and closing the editor sends it. Nothing that arrives from the server
 * overwrites a draft that has not gone out yet — and a send that fails keeps the draft
 * on screen, says so, and can be tried again.
 *
 * One panel serves three subjects, and they are told apart by `subject.kind` and by whether the
 * block is an occurrence rather than by three components that would drift apart within a month:
 *
 *   a block       one thing you planned, with a Repeat control that turns it into a rule
 *   a day of a rule  the same fields, going to that one day, with the option to take the day out
 *   the rule      the fields plus when it starts, when it ends and whether it is on
 *
 * The choice between the second and the third is the panel's own switch, not a second panel:
 * "edit this occurrence" and "edit the routine" are two readings of one thing, and pushing one
 * of them behind a modal is how a person edits the wrong one.
 */
export default function Editor({
  subject, day, onSave, onRepeat, onSkip, onReset, onRemove, onHalf, onClose, steps,
}) {
  const block = subject.block
  const routine = subject.routine
  const onRoutine = subject.kind === 'routine'
  const occurrence = block != null && isOccurrence(block)
  const shown = onRoutine ? routine : block

  const [draft, setDraft] = useState({
    title: shown.title,
    notes: shown.notes,
    duration_min: shown.duration_min,
  })
  const [status, setStatus] = useState('idle') // idle | saving | saved | failed
  const [retry, setRetry] = useState(null) // the changes that did not get through

  // The repeat control's own state. On the rule half it starts from the rule and every change
  // is a write; on a block it starts at "Never" and choosing something is what turns the block
  // into a rule. `weeks` and `days` are held here either way so that picking a kind that needs
  // more than one answer does not throw away the answer already given.
  const [repeat, setRepeat] = useState(() => (onRoutine ? routine.recurrence_kind : 'never'))
  const [days, setDays] = useState(() => (onRoutine ? routine.weekdays ?? [] : []))
  const [weeks, setWeeks] = useState(() => (onRoutine ? routine.interval_weeks ?? 1 : 1))

  // A prop can change under us; the newest one is what a save should call.
  const newest = useRef({ onSave, shown })
  newest.current = { onSave, shown }

  const waiting = useRef(null) // typed, not sent yet
  const timer = useRef(null)
  const panel = useRef(null)

  const deliver = useCallback(async (changes) => {
    if (!Object.keys(changes).length) return
    setStatus('saving')
    try {
      await newest.current.onSave(changes)
      setRetry(null)
      setStatus('saved')
    } catch {
      setRetry(changes)
      setStatus('failed')
    }
  }, [])

  /** Typed fields: show it immediately, send it once the typing stops. */
  const type = useCallback(
    (changes) => {
      setDraft((current) => ({ ...current, ...changes }))
      waiting.current = { ...(waiting.current || {}), ...changes }

      if ('title' in changes && !String(changes.title).trim()) {
        // An empty title is not a title. Keep it on screen, send nothing, and let the
        // next keystroke — or leaving the field — decide what happens to it.
        if (timer.current) {
          clearTimeout(timer.current)
          timer.current = null
        }
        return
      }

      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        timer.current = null
        const held = waiting.current
        waiting.current = null
        if (held) deliver(held)
      }, HOLD)
    },
    [deliver],
  )

  /** A button: there is nothing to wait for. */
  const act = useCallback(
    (changes) => {
      const held = waiting.current
      waiting.current = null
      if (timer.current) {
        clearTimeout(timer.current)
        timer.current = null
      }
      deliver({ ...(held || {}), ...changes })
    },
    [deliver],
  )

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    const held = waiting.current
    waiting.current = null
    if (!held) return

    if ('title' in held && !String(held.title).trim()) {
      // Never send a blank title: put the saved one back and send the rest.
      setDraft((current) => ({ ...current, title: newest.current.shown.title }))
      delete held.title
      if (!Object.keys(held).length) return
    }
    deliver(held)
  }, [deliver])

  // Leaving this block, or the editor: send whatever is still waiting.
  useEffect(() => () => flush(), [flush])

  // Focus goes to the panel rather than the title field. This is a phone-first app, and
  // opening the keyboard the moment a block is tapped is not a kindness; Escape and Tab
  // still work from here.
  useEffect(() => {
    panel.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== 'Escape') return
      flush()
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flush, onClose])

  /** Choosing a repeat for a block: the rule is created from the block's own fields, so there
   *  is nothing else to ask for. Custom weekdays is the one that needs a second answer, and it
   *  waits for the button rather than sending a rule with no days in it. */
  const chooseRepeat = (kind) => {
    setRepeat(kind)
    const picked = weekdaysFor(kind, block?.day ?? day)
    if (picked.length) setDays(picked)
    if (kind === 'never' || kind === 'selected_weekdays') return
    onRepeat({ recurrence_kind: kind, weekdays: picked.length ? picked : days, interval_weeks: weeks })
  }

  /** The same control on the rule half: every change is a write to the rule. */
  const changeRepeat = (kind) => {
    setRepeat(kind)
    // Moving to custom days seeds from the day the rule already lands on, so the set you are
    // about to edit starts from a day you recognise — and so the write cannot be one the API
    // refuses for having no days in it.
    const picked = kind === 'selected_weekdays' && !days.length
      ? [isoWeekday(routine.start_date)]
      : weekdaysFor(kind, routine.start_date)
    if (picked.length) setDays(picked)
    act({
      recurrence_kind: kind,
      weekdays: picked.length ? picked : days,
      interval_weeks: weeks,
    })
  }

  const weekdayRow = (onPick) => (
    <div className="weekdays" role="group" aria-label="Days of the week">
      {WEEKDAYS.map((n, i) => (
        <button
          type="button"
          key={n}
          className={`weekday${days.includes(n) ? ' on' : ''}`}
          // The letter is what you see; the name is what a screen reader says, because "T"
          // twice in one row is not a day of the week.
          aria-label={['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
            'Sunday'][i]}
          aria-pressed={days.includes(n)}
          // The last day cannot be taken out: the API refuses a custom repeat with no days,
          // and a button that fails on press is worse than one that is not offered.
          disabled={days.length === 1 && days.includes(n)}
          onClick={() => onPick(n)}
        >
          {WEEKDAY_LABELS[i]}
        </button>
      ))}
    </div>
  )

  return (
    <aside
      className="editor"
      role="dialog"
      aria-label={onRoutine ? 'Routine details' : 'Block details'}
      tabIndex={-1}
      ref={panel}
    >
      <div className="sheet-grip" />

      <div className="editor-head">
        <input
          className="title-input"
          value={draft.title}
          onChange={(e) => type({ title: e.target.value })}
          onBlur={flush}
          aria-label={onRoutine ? 'Routine title' : 'Title'}
        />
        <button type="button" className="close" onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <div className="editor-status" data-state={status} aria-live="polite">
        {status === 'saving' && <span className="muted">Saving…</span>}
        {status === 'saved' && <span className="muted">Saved</span>}
        {status === 'failed' && (
          <>
            <span>Couldn’t save</span>
            <button type="button" onClick={() => deliver(retry)}>
              Retry
            </button>
          </>
        )}
      </div>

      {/* Which thing is being changed. Said plainly, because getting this wrong is the whole
          risk of having a routine: the same panel edits one day or every one. */}
      {routine && (
        <div className="routine-head" data-on={onRoutine ? 'routine' : 'day'}>
          <p className="routine-what">
            <Glyph name="repeat" />
            {onRoutine ? (
              <>
                The rule for <b>{routine.title}</b> — {routine.summary}. Every day it has not
                been told otherwise changes with it.
              </>
            ) : (
              <>
                One day of <b>{routine.title}</b> — {routine.summary}
              </>
            )}
          </p>
          {block && (
            <div className="halves" role="group" aria-label="What this edit applies to">
              <button
                type="button"
                data-half="day"
                className={onRoutine ? '' : 'on'}
                aria-pressed={!onRoutine}
                onClick={() => onHalf('day')}
              >
                This day
              </button>
              <button
                type="button"
                data-half="routine"
                className={onRoutine ? 'on' : ''}
                aria-pressed={onRoutine}
                onClick={() => onHalf('routine')}
              >
                The routine
              </button>
            </div>
          )}
        </div>
      )}

      <label className="field">
        <span>Icon</span>
        <div className="icon-grid">
          <button type="button"
            className={`icon-pick${shown.icon ? '' : ' on'}`}
            onClick={() => act({ icon: '' })}
            aria-label="No icon"
          >
            –
          </button>
          {ICONS.map((glyph) => (
            <button type="button"
              key={glyph}
              className={`icon-pick${shown.icon === glyph ? ' on' : ''}`}
              onClick={() => act({ icon: glyph })}
              aria-label={`Icon ${glyph}`}
            >
              {glyph}
            </button>
          ))}
        </div>
      </label>

      {/* A day of a routine is not moved to another day: the rule decides which days it has,
          and moving one would be asking for a different rule. The Day field is a block's. */}
      {!routine && !occurrence && (
        <label className="field">
          <span>Day</span>
          <div className="dur-row">
            <input
              type="date"
              value={block.day ?? day}
              onChange={(e) => {
                const next = e.target.value
                if (!next) return
                // The day and the start time travel together, so an inbox item given a
                // date lands at 9am on it rather than being refused by the API.
                act({ day: next, start_min: block.start_min ?? 9 * 60 })
              }}
              aria-label="Day"
            />
          </div>
        </label>
      )}

      <label className="field">
        <span>Starts</span>
        <div className="dur-row">
          <input
            type="time"
            value={shown.start_min == null ? '' : hhmm(shown.start_min)}
            onChange={(e) => {
              const [h, m] = e.target.value.split(':').map(Number)
              if (Number.isFinite(h)) {
                // The day you are looking at, not today: scheduling a task while
                // reading Thursday's plan should put it on Thursday.
                act(routine || occurrence
                  ? { start_min: h * 60 + m }
                  : { day: block.day ?? day, start_min: h * 60 + m })
              }
            }}
            aria-label="Start time"
          />
          {!routine && !occurrence && block.start_min != null && (
            <button type="button" onClick={() => act({ unschedule: true })}>
              Back to anytime
            </button>
          )}
        </div>
      </label>

      <label className="field">
        <span>Length</span>
        <div className="dur-row">
          <input
            type="range"
            min="5"
            max="480"
            step="5"
            value={draft.duration_min}
            onChange={(e) => type({ duration_min: Number(e.target.value) })}
            onBlur={flush}
            onPointerUp={flush}
          />
          <b>{durText(draft.duration_min)}</b>
        </div>
      </label>

      <label className="field">
        <span>Colour</span>
        <div className="swatches">
          {COLORS.map((c) => (
            <button type="button"
              key={c}
              className={`swatch c-${c}${shown.color === c ? ' on' : ''}`}
              onClick={() => act({ color: c })}
              aria-label={c}
            />
          ))}
        </div>
      </label>

      {/* Repeat. On a block it is the control that makes one; on the rule it is the control
          that says which days it lands on. Never both, because a block that belongs to a rule
          is not a block any more. */}
      {!routine && !occurrence && (
        <label className="field repeat-field">
          <span>Repeat</span>
          {block.day === null || block.start_min == null ? (
            // A rule is a day of the week and an hour. An inbox item has neither yet, so the
            // control is absent and says why rather than being offered and then refused.
            <span className="field-note">
              A routine needs a day and a time. Give this one a day first.
            </span>
          ) : (
            <>
              <div className="dur-row">
                <select
                  className="repeat-kind"
                  value={repeat}
                  onChange={(e) => chooseRepeat(e.target.value)}
                  aria-label="Repeat"
                >
                  <option value="never">Never</option>
                  {REPEATS.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
              {repeat === 'selected_weekdays' && (
                <>
                  {weekdayRow((n) => setDays(toggleWeekday(days, n)))}
                  <button
                    type="button"
                    className="repeat-go"
                    disabled={!days.length}
                    onClick={() => onRepeat({
                      recurrence_kind: 'selected_weekdays', weekdays: days, interval_weeks: 1,
                    })}
                  >
                    Repeat on {days.length === 1 ? 'this day' : 'these days'}
                  </button>
                </>
              )}
              <span className="field-note">
                Turning this on makes today’s block a routine. It stops being a one-off, and
                the panel switches to the rule so you can say when it ends.
              </span>
            </>
          )}
        </label>
      )}

      {onRoutine && (
        <label className="field repeat-field">
          <span>Repeats</span>
          <div className="dur-row">
            <select
              className="repeat-kind"
              value={repeat}
              onChange={(e) => changeRepeat(e.target.value)}
              aria-label="Repeat"
            >
              {REPEATS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.value === 'weekly_interval' ? everyWeeks(weeks) : r.label}
                </option>
              ))}
            </select>
            {repeat === 'weekly_interval' && (
              <input
                className="weeks-input"
                type="number"
                min="1"
                max="52"
                value={weeks}
                onChange={(e) => {
                  const n = Math.max(1, Math.min(52, Number(e.target.value) || 1))
                  setWeeks(n)
                  act({ interval_weeks: n })
                }}
                aria-label="Every how many weeks"
              />
            )}
          </div>
          {repeat === 'selected_weekdays'
            && weekdayRow((n) => {
              const next = toggleWeekday(days, n)
              setDays(next)
              act({ weekdays: next })
            })}
        </label>
      )}

      {onRoutine && (
        <>
          <label className="field">
            <span>From</span>
            <div className="dur-row">
              <input
                type="date"
                value={routine.start_date}
                onChange={(e) => e.target.value && act({ start_date: e.target.value })}
                aria-label="First day"
              />
            </div>
          </label>
          <label className="field">
            <span>Until</span>
            <div className="dur-row">
              <input
                type="date"
                value={routine.end_date ?? ''}
                onChange={(e) => act({ end_date: e.target.value || null })}
                aria-label="Last day"
              />
              {routine.end_date && (
                <button type="button" onClick={() => act({ end_date: null })}>
                  No end
                </button>
              )}
            </div>
          </label>
        </>
      )}

      <Steps
        lines={stepsOf(shown)}
        where={whereSteps(subject)}
        onAdd={steps.add}
        onRename={steps.rename}
        onRemove={steps.remove}
        onTick={steps.tick}
      />

      <label className="field">
        <span>Notes</span>
        <textarea
          rows="3"
          value={draft.notes}
          onChange={(e) => type({ notes: e.target.value })}
          onBlur={flush}
        />
      </label>

      <div className="editor-actions">
        {onRoutine ? (
          <>
            <button
              type="button"
              className={routine.enabled ? '' : 'primary'}
              onClick={() => act({ enabled: !routine.enabled })}
            >
              {routine.enabled ? 'Turn off' : 'Turn on'}
            </button>
            <button type="button" className="danger" onClick={onRemove}>
              Delete the routine
            </button>
          </>
        ) : (
          <>
            {occurrence ? (
              <>
                <button type="button" className="danger" onClick={onSkip}>
                  Skip this day
                </button>
                {differsFromRoutine(block, routine) && (
                  <button type="button" onClick={onReset}>
                    Back to the routine
                  </button>
                )}
              </>
            ) : (
              <>
                {block.day === null ? (
                  <span className="muted">In the inbox — drag it onto the timeline.</span>
                ) : (
                  <button type="button" onClick={() => act({ unschedule: true })}>
                    Back to inbox
                  </button>
                )}
              </>
            )}
            <button
              type="button"
              className={block.done ? 'primary' : ''}
              onClick={() => act({ done: !block.done })}
            >
              {block.done ? 'Done' : 'Mark done'}
            </button>
            {!occurrence && (
              <button type="button" className="danger" onClick={onRemove}>Delete</button>
            )}
          </>
        )}
      </div>
    </aside>
  )
}
