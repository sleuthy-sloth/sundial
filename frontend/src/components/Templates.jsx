import { useCallback, useEffect, useRef, useState } from 'react'

import { durText, hhmm } from '../time'
import {
  NEW_ITEM, canApply, describeTemplate, reorder, withItem, withoutItem,
} from '../templates'

// How long the typing has to stop before the list is sent. The whole list goes in one PUT, so a
// keystroke-per-request would rewrite every line of a template for every letter typed into one
// of them.
const HOLD = 500

// The same eight the API validates against and the block editor draws. Kept here rather than
// imported from `Editor.jsx`, which is a panel for a day rather than a source of colours.
const COLORS = ['slate', 'sky', 'violet', 'amber', 'emerald', 'rose', 'teal', 'indigo']

/**
 * The templates you have, and what is in them.
 *
 * Under You rather than on the day, and for the same reason routines are: a template has no day
 * on screen until it is applied to one, so the place that lists what this copy holds is the only
 * way back to it. The one thing here that acts on a day says which day, out loud.
 *
 * Editing the contents is a draft like the editor's fields: the list on screen is what you are
 * writing, and it goes out as one PUT when the typing stops or when you leave a field. A line
 * with no name is not sent at all — the API refuses the whole list for one blank title, so the
 * panel says which one is missing a name instead of sending it and showing a refusal.
 *
 * Nothing here counts anything at you and nothing is judged: an empty template says it is empty,
 * and a template with no times says what it is made of.
 */
export default function Templates({ templates, note, today, actions }) {
  const [openId, setOpenId] = useState(null)
  const [draftNames, setDraftNames] = useState({})
  const [draft, setDraft] = useState('')

  const create = (event) => {
    event.preventDefault()
    const name = draft.trim()
    if (!name) return
    setDraft('')
    actions.create(name)
  }

  return (
    <>
      <h2>Templates</h2>

      <form className="template-new" onSubmit={create}>
        <input
          className="template-new-name"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Name a day you repeat"
          aria-label="New template name"
        />
        <button type="submit" className="template-make" disabled={!draft.trim()}>
          Make it
        </button>
      </form>

      {note && <p className="note template-note">{note}</p>}

      {templates.length === 0 ? (
        <p className="note">
          No templates yet. A template is a day you write once — a workday, a weekend reset, a
          travel day — and can put on any day you like, without it repeating on its own.
        </p>
      ) : (
        <ul className="template-list">
          {templates.map((template) => (
            <li key={template.id} className="template-row" data-template-id={template.id}>
              <div className="template-head">
                <input
                  className="template-name"
                  value={draftNames[template.id] ?? template.name}
                  onChange={(e) =>
                    setDraftNames((now) => ({ ...now, [template.id]: e.target.value }))}
                  onBlur={(e) => {
                    const name = e.target.value.trim()
                    if (!name || name === template.name) {
                      setDraftNames((now) => ({ ...now, [template.id]: template.name }))
                      return
                    }
                    actions.rename(template.id, name)
                  }}
                  aria-label={`${template.name} — its name`}
                />
                <span className="template-what">{describeTemplate(template)}</span>
              </div>

              <div className="template-actions">
                <button
                  type="button"
                  className="template-topen"
                  data-template-act="contents"
                  aria-expanded={openId === template.id}
                  onClick={() => setOpenId(openId === template.id ? null : template.id)}
                >
                  {openId === template.id ? 'Close' : 'Edit contents'}
                </button>
                {/* The one control here that acts on a day, and it names the day: the day view
                    can be showing any date, and "apply" with no day on it would be a guess. */}
                <button
                  type="button"
                  className="template-do template-apply-to"
                  data-template-act="apply"
                  disabled={!canApply(template)}
                  onClick={() => actions.apply(template.id, today)}
                >
                  Apply to today
                </button>
                <button
                  type="button"
                  className="template-do template-copy"
                  data-template-act="duplicate"
                  onClick={() => actions.duplicate(template.id)}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="template-do danger template-remove"
                  data-template-act="delete"
                  onClick={() => actions.remove(template.id)}
                >
                  Delete
                </button>
              </div>

              {openId === template.id && (
                <Contents key={template.id} template={template} onSave={actions.saveItems} />
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="note">
        Applying adds blocks to the day you pick and changes nothing that is already there. A
        line with no time lands in Anytime. Nothing here repeats on its own.
      </p>
    </>
  )
}

/**
 * One template's lines: what each is called, when it is, how long it lasts, which colour, and
 * where it sits in the order.
 *
 * Mounted only while a template is open, which is what lets the draft be plain local state: the
 * list is seeded when the panel opens and is the truth until the typing stops. Removing the
 * panel is how you stop editing, and leaving a field sends what is waiting.
 */
function Contents({ template, onSave }) {
  const [items, setItems] = useState(template.items)
  const [status, setStatus] = useState('idle') // idle | saving | saved | failed

  const waiting = useRef(null)
  const timer = useRef(null)
  const newest = useRef({ id: template.id, onSave })
  newest.current = { id: template.id, onSave }

  const deliver = useCallback(async (list) => {
    setStatus('saving')
    try {
      await newest.current.onSave(newest.current.id, list)
      setStatus('saved')
    } catch {
      setStatus('failed')
    }
  }, [])

  /** Show it at once, send it when the typing stops. */
  const push = (list, now = false) => {
    setItems(list)
    waiting.current = list
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    if (now) {
      const held = waiting.current
      waiting.current = null
      deliver(held)
      return
    }
    timer.current = setTimeout(() => {
      timer.current = null
      const held = waiting.current
      waiting.current = null
      if (held) deliver(held)
    }, HOLD)
  }

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    const held = waiting.current
    waiting.current = null
    if (held) deliver(held)
  }, [deliver])

  useEffect(() => () => flush(), [flush])

  const change = (index, changes, now = false) =>
    push(items.map((item, i) => (i === index ? { ...item, ...changes } : item)), now)

  // The API refuses the whole list for one nameless line, so none is sent while one is blank.
  const nameless = items.some((item) => !String(item.title).trim())

  return (
    <div className="template-contents">
      {items.map((item, index) => (
        <div className="template-item" key={index}>
          <input
            className="item-title"
            value={item.title}
            onChange={(e) => change(index, { title: e.target.value })}
            onBlur={flush}
            aria-label={`Line ${index + 1} name`}
          />

          <span className="item-when">
            <input
              type="time"
              className="item-time"
              value={item.start_min == null ? '' : hhmm(item.start_min)}
              onChange={(e) => {
                const [h, m] = e.target.value.split(':').map(Number)
                // Cleared means Anytime: the field going empty is the whole of that change, and
                // it is how a line that was at an hour goes back to having none.
                change(index, { start_min: Number.isFinite(h) ? h * 60 + m : null }, true)
              }}
              aria-label={`Line ${index + 1} time`}
            />
            <span className="item-anytime">{item.start_min == null ? 'Anytime' : ''}</span>
          </span>

          <span className="item-length">
            <input
              type="number"
              className="item-minutes"
              min="5"
              max="480"
              step="5"
              value={item.duration_min}
              onChange={(e) =>
                change(index, { duration_min: Number(e.target.value) || 5 }, true)}
              aria-label={`Line ${index + 1} length in minutes`}
            />
            <span className="item-units">{durText(item.duration_min)}</span>
          </span>

          <select
            className="item-color"
            value={item.color}
            onChange={(e) => change(index, { color: e.target.value }, true)}
            aria-label={`Line ${index + 1} colour`}
          >
            {COLORS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <span className="item-move">
            <button
              type="button"
              className="item-up"
              disabled={index === 0}
              onClick={() => push(reorder(items, index, index - 1), true)}
              aria-label={`Move line ${index + 1} up`}
            >
              ↑
            </button>
            <button
              type="button"
              className="item-down"
              disabled={index === items.length - 1}
              onClick={() => push(reorder(items, index, index + 1), true)}
              aria-label={`Move line ${index + 1} down`}
            >
              ↓
            </button>
            <button
              type="button"
              className="item-remove danger"
              onClick={() => push(withoutItem(items, index), true)}
              aria-label={`Remove line ${index + 1}`}
            >
              ×
            </button>
          </span>
        </div>
      ))}

      <div className="template-contents-foot">
        <button type="button" className="item-add" onClick={() => push(withItem(items), true)}>
          Add a line
        </button>
        <span className="template-status" data-state={status} aria-live="polite">
          {status === 'saving' && <span className="muted">Saving…</span>}
          {status === 'saved' && <span className="muted">Saved</span>}
          {status === 'failed' && <span className="muted">Couldn’t save</span>}
        </span>
      </div>

      {nameless && (
        <p className="note item-blocked">Every line needs a name before this is saved.</p>
      )}
    </div>
  )
}
