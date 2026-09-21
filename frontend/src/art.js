/**
 * The one rule about when the ledger's artwork appears.
 *
 * The pictures themselves live beside the component that draws them (LedgerArt.jsx), because
 * they are bundler imports and this module has to stay importable by a test runner that knows
 * nothing about .webp files. What is here is the decision, which is worth testing on its own.
 */

/**
 * Is the day actually finished, or merely empty?
 *
 * Only a day that had plans and has none left counts. An empty day is empty — it gets the
 * empty state, not a medal — and so does a day you are looking at from the outside, because
 * "finished" is a fact about today, not a fact about a date.
 *
 * `done` arrives from SQLite as 0 or 1 rather than as a boolean, which is why this tests it
 * for truth rather than comparing it to `true`.
 */
export function dayIsClear(blocks = [], inbox = [], day = '', today = '') {
  if (day !== today) return false
  if (inbox.length > 0) return false // something is still waiting for a time
  if (blocks.length === 0) return false // nothing was planned, so nothing is done
  return blocks.every((b) => b.done)
}
