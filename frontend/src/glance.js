// The extension is not optional: this module is run directly by `node --test`, which
// resolves the file rather than bundling it, and Vite's bare './time' is not a path it can find.
import { durText, hhmm } from './time.js'

/** What the day is doing right now, in one line.
 *
 *  The timeline draws a line at the current minute and the plan lists everything in it, but
 *  neither answers the question you open the app to ask: which block am I meant to be in, and how
 *  long is left of it. That is this module's whole job.
 *
 *  A pure function rather than a component, so the answer can be asserted at a chosen minute
 *  instead of waiting for the clock to reach one.
 */

/** The block you are in, or the next one coming, or nothing.
 *
 *  Half-open, like the timeline: a block starting 09:00 for 90 minutes is current at 10:29 and
 *  over at 10:30.
 *
 *  A ticked-off block is never current. "Now" pointing at work you have already finished is a
 *  small lie, and this app does not need to tell one.
 *
 *  Untimed work is not a candidate either: "anytime" has no hour to be in, and pretending it does
 *  would turn the whole inbox into a claim about what you are doing.
 */
export function glanceAt(blocks, nowMin) {
  const timed = blocks
    .filter((b) => !b.done && b.start_min != null)
    .sort((a, b) => a.start_min - b.start_min)

  const current = timed.find(
    (b) => b.start_min <= nowMin && nowMin < b.start_min + b.duration_min,
  )
  if (current) {
    const until = current.start_min + current.duration_min
    return {
      kind: 'now',
      title: current.title,
      when: `until ${hhmm(until)}`,
      left: `${durText(until - nowMin)} left`,
    }
  }

  const next = timed.find((b) => b.start_min > nowMin)
  if (next) {
    return {
      kind: 'next',
      title: next.title,
      when: `at ${hhmm(next.start_min)}`,
      left: `in ${durText(next.start_min - nowMin)}`,
    }
  }

  // Nothing is running and nothing timed is coming. The sections below already show what is left,
  // so this line says nothing rather than saying "nothing".
  return null
}
