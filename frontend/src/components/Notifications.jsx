import { useEffect, useState } from 'react'

import { api } from '../api'
import { availability, current, disable, enable, explain, testResultMessage } from '../push'
import Switch from './Switch'

/**
 * Turning on "tell me when a block starts".
 *
 * It is off until it is asked for, and the state shown is the browser's answer rather than
 * what was last clicked: a subscription can be dropped by the push service, or cleared
 * along with the site's data, and a panel that only remembered its own last click would go
 * on claiming to be on. Nothing here is a preference the app stores — the subscription is
 * the setting.
 *
 * The caveat in the note is deliberate and belongs on screen. sundial sends this itself and
 * can only send while it is running, so a notification about nine o'clock needs the app up
 * at nine o'clock. That is a real limit of a thing that owns one file in your home
 * directory, and a panel that hid it would be teaching you to distrust the feature instead.
 */
export default function Notifications() {
  const [state, setState] = useState('checking')
  const [why, setWhy] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    async function look() {
      const blocked = availability()
      if (blocked !== 'ready') {
        if (alive) {
          setState('blocked')
          setWhy(explain(blocked))
        }
        return
      }
      const existing = await current().catch(() => null)
      if (alive) setState(existing ? 'on' : 'off')
    }
    look()
    return () => {
      alive = false
    }
  }, [])

  async function turnOn() {
    setBusy(true)
    setNote('')
    try {
      await enable(api)
      setState('on')
      setNote('On for this device.')
    } catch (err) {
      // The sentence from push.js names the step that refused, which is the difference
      // between "turn it on in your browser settings" and "try again".
      setState('off')
      setNote(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function turnOff() {
    setBusy(true)
    setNote('')
    try {
      const wasOn = await disable(api)
      setState('off')
      setNote(wasOn ? 'Off for this device.' : 'Nothing was on.')
    } catch (err) {
      setNote(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function sendTest() {
    setBusy(true)
    setNote('')
    try {
      const result = await api.testPush()
      setNote(testResultMessage(result))
    } catch (err) {
      setNote(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h2>Notifications</h2>
      <div className="set-row push-row">
        <span className="set-label">When a block starts</span>
        <span className="set-value push-state">
          {state === 'checking' ? 'checking\u2026' : state === 'on' ? 'On' : 'Off'}
        </span>
        {state !== 'blocked' && (
          <Switch
            className="push-toggle"
            checked={state === 'on'}
            disabled={busy || state === 'checking'}
            onChange={(on) => (on ? turnOn() : turnOff())}
            label="Tell me when a block starts"
          />
        )}
      </div>

      {state === 'blocked' && <p className="note push-blocked">{why}</p>}

      {state === 'on' && (
        <div className="set-row push-controls">
          <button
            type="button"
            className="push-btn push-test"
            onClick={sendTest}
            disabled={busy}
          >
            Send one now
          </button>
        </div>
      )}

      {note && <p className="note">{note}</p>}
      <p className="note push-limit">
        One notification at the hour a block begins. Nothing else: no reminders, no summary,
        and no count of what you did not get to. sundial sends these itself, so it can only
        send while it is running &mdash; a notification about nine o&rsquo;clock needs the app
        up at nine o&rsquo;clock.
      </p>
    </>
  )
}
