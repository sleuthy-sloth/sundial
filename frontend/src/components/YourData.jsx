import { useRef, useState } from 'react'

import { api } from '../api'
import { describe, summarize } from '../datafile'

/**
 * Your data, and the promise that you can take it and go.
 *
 * Two controls, and they are not symmetrical: exporting is a read you can do as often as you
 * like, and importing replaces everything and cannot be undone. So the import is two steps, and
 * the second step says what it is about to do rather than asking "are you sure?" — a question
 * nobody can answer without being told what it is asking about.
 *
 * The export deliberately does not include the phone's notification setting. That setting is a
 * capability — anything holding the endpoint can send to that device — so it has no business in
 * a file people mail to themselves. Which is also why importing cannot unsubscribe you: the
 * table is simply not touched.
 */
export default function YourData() {
  const [note, setNote] = useState('')
  const [ready, setReady] = useState(null)
  const [busy, setBusy] = useState(false)
  const picker = useRef(null)

  async function save() {
    setBusy(true)
    try {
      const { document: payload, filename } = await api.exportAll()
      const url = URL.createObjectURL(
        new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' }),
      )
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      const seen = summarize(payload)
      setNote(`Saved ${filename}: ${seen.says}.`)
    } catch (err) {
      setNote(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function choose(event) {
    const file = event.target.files?.[0]
    // Clear it, or choosing the same file twice in a row fires nothing the second time.
    event.target.value = ''
    if (!file) return
    let payload
    try {
      payload = JSON.parse(await file.text())
    } catch {
      setReady(null)
      setNote(`${file.name} is not a JSON file.`)
      return
    }
    const seen = summarize(payload)
    if (!seen.ok) {
      setReady(null)
      setNote(`${file.name}: ${seen.why}`)
      return
    }
    setReady({ payload, name: file.name, says: seen.says })
    setNote('')
  }

  async function replace() {
    setBusy(true)
    try {
      const answer = await api.importAll(ready.payload)
      setReady(null)
      setNote(
        `Replaced everything: ${describe(answer.replaced)}. ` +
          `Your phone's notification setting was left alone, and what was here before is ` +
          `kept at ${answer.kept}.`,
      )
    } catch (err) {
      setNote(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h2>Your data</h2>
      <p className="note">
        Everything sundial holds, as one readable file. Not the calendar passwords — those live
        in files beside the app and are never read for this — and not your phone&rsquo;s
        notification setting, because an endpoint can send to that device.
      </p>

      <div className="data-row">
        <button type="button" className="data-btn data-export" onClick={save} disabled={busy}>
          Export as JSON
        </button>
        <input
          ref={picker}
          className="data-file"
          type="file"
          accept="application/json,.json"
          onChange={choose}
          hidden
        />
        <button
          type="button"
          className="data-btn data-import"
          onClick={() => picker.current?.click()}
          disabled={busy}
        >
          Replace from a file
        </button>
      </div>

      {ready && (
        <div className="data-confirm">
          <p className="note">
            <strong>{ready.name}</strong> holds {ready.says}. Importing replaces everything in
            sundial with it, and that cannot be undone — though a copy of what is there now is
            kept, and its path is in the message afterwards.
          </p>
          <div className="data-actions">
            <button
              type="button"
              className="data-btn data-replace"
              onClick={replace}
              disabled={busy}
            >
              Replace everything
            </button>
            <button
              type="button"
              className="data-btn data-cancel"
              onClick={() => {
                setReady(null)
                setNote('')
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {note && <p className="note data-note">{note}</p>}
    </>
  )
}
