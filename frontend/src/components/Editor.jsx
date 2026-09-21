import { useCallback, useEffect, useRef, useState } from 'react'

import { ICONS } from '../icons'
import { durText, hhmm } from '../time'

const COLORS = ['slate', 'sky', 'violet', 'amber', 'emerald', 'rose', 'teal', 'indigo']

// How long the typing has to stop before what was typed is sent.
const HOLD = 450

/** The editor owns what is on screen while you type.
 *
 * The server's copy of a block arrives a round trip after each write, and a round trip
 * is exactly when the text you are still writing would be replaced by the text you
 * started from. So the fields keep their own draft: a pause sends it, leaving the field
 * sends it, and closing the editor sends it. Nothing that arrives from the server
 * overwrites a draft that has not gone out yet — and a send that fails keeps the draft
 * on screen, says so, and can be tried again.
 */
export default function Editor({ block, day, onSave, onRemove, onClose }) {
  const [draft, setDraft] = useState({
    title: block.title,
    notes: block.notes,
    duration_min: block.duration_min,
  })
  const [status, setStatus] = useState('idle') // idle | saving | saved | failed
  const [retry, setRetry] = useState(null) // the changes that did not get through

  // A prop can change under us; the newest one is what a save should call.
  const newest = useRef({ onSave, block })
  newest.current = { onSave, block }

  const waiting = useRef(null) // typed, not sent yet
  const timer = useRef(null)
  const panel = useRef(null)

  const deliver = useCallback(async (changes) => {
    setStatus('saving')
    try {
      await newest.current.onSave(newest.current.block.id, changes)
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
      setDraft((current) => ({ ...current, title: newest.current.block.title }))
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

  return (
    <aside
      className="editor"
      role="dialog"
      aria-label="Block details"
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
          aria-label="Title"
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

      <label className="field">
        <span>Icon</span>
        <div className="icon-grid">
          <button type="button"
            className={`icon-pick${block.icon ? '' : ' on'}`}
            onClick={() => act({ icon: '' })}
            aria-label="No icon"
          >
            –
          </button>
          {ICONS.map((glyph) => (
            <button type="button"
              key={glyph}
              className={`icon-pick${block.icon === glyph ? ' on' : ''}`}
              onClick={() => act({ icon: glyph })}
              aria-label={`Icon ${glyph}`}
            >
              {glyph}
            </button>
          ))}
        </div>
      </label>

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

      <label className="field">
        <span>Starts</span>
        <div className="dur-row">
          <input
            type="time"
            value={block.start_min == null ? '' : hhmm(block.start_min)}
            onChange={(e) => {
              const [h, m] = e.target.value.split(':').map(Number)
              if (Number.isFinite(h)) {
                // The day you are looking at, not today: scheduling a task while
                // reading Thursday's plan should put it on Thursday.
                act({ day: block.day ?? day, start_min: h * 60 + m })
              }
            }}
            aria-label="Start time"
          />
          {block.start_min != null && (
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
              className={`swatch c-${c}${block.color === c ? ' on' : ''}`}
              onClick={() => act({ color: c })}
              aria-label={c}
            />
          ))}
        </div>
      </label>

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
        {block.day === null ? (
          <span className="muted">In the inbox — drag it onto the timeline.</span>
        ) : (
          <button type="button" onClick={() => act({ unschedule: true })}>Back to inbox</button>
        )}
        <button type="button" className={block.done ? 'primary' : ''} onClick={() => act({ done: !block.done })}>
          {block.done ? 'Done' : 'Mark done'}
        </button>
        <button type="button" className="danger" onClick={onRemove}>Delete</button>
      </div>
    </aside>
  )
}
