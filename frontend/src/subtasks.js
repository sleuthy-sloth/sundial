/** A task's checklist: the steps it holds, and where a write about one of them goes.
 *
 *  A pure module, like `templates.js` and `rollover.js`, because everything in it is worth
 *  asserting without a browser. The server owns the order — a line carries the `sort_order` it
 *  was written at — and owns every refusal. What lives here is the local half: which list of
 *  steps is on screen, which route changes one, and the list edits made between saves.
 *
 *  Three different things can hold a checklist, and they are three different shapes, which is
 *  the whole reason this file exists. A *task* holds lines that are blocks of their own, so
 *  ticking one is a PATCH to that row. A *routine* holds definitions: the steps belong to the
 *  rule and are drawn on every day of it, while ticking one is a fact about a single day that
 *  goes to that day's occurrence — the rule's own editor has no day to tick. A *template item*
 *  holds steps that are part of the item list, saved with it. `whereSteps` is the one place that
 *  decision is made.
 *
 *  Nothing here counts anything. The steps are on the screen under their task, which is the
 *  progress; a "2 of 3" beside the title would be a score, and this app does not keep those.
 */

import { isOccurrence } from './routines.js'

/** The steps a task, a rule or a template item holds. Always an array.
 *
 *  A client that has to test for the key's absence is a client that will one day read "no
 *  steps" and "this shape is new to me" as the same thing — and the API sends the key on every
 *  block for exactly that reason. */
export const stepsOf = (holder) => (Array.isArray(holder?.subtasks) ? holder.subtasks : [])

/** Whether anything draws at all. An empty checklist renders nothing, which is what keeps a
 *  task with no steps looking exactly as it did before any of this existed. */
export const hasSteps = (holder) => stepsOf(holder).length > 0

/** What a template step starts as when you add one. A word rather than an empty box, so the
 *  list is never in a state the API refuses — the same reasoning as `NEW_ITEM`. */
export const NEW_STEP = { title: 'New step' }

/** Add a step at the end (a template item's draft list: positional, no ids yet). */
export const withStep = (steps = [], step = NEW_STEP) => [...steps, { ...step }]

/** Take the step at `index` out. */
export const withoutStep = (steps, index) => steps.filter((_, i) => i !== index)

/** Rename the step at `index`, leaving the rest of the list — and its order — alone. */
export const changeStep = (steps, index, title) =>
  steps.map((step, i) => (i === index ? { ...step, title } : step))

/** The steps as the template's own body sends them: names, in order, and nothing else. Ids and
 *  `sort_order` are the server's to assign, and a step has no hour or colour of its own. */
export const payloadSteps = (steps = []) =>
  steps.map((step) => ({ title: String(step?.title ?? '').trim() }))

/** Whether every step in the list has a name. One blank line is a body the API refuses whole,
 *  so the panel holds the save rather than sending it — the same rule the items follow. */
export const namesEveryStep = (steps = []) =>
  steps.every((step) => String(step?.title ?? '').trim().length > 0)

/**
 * Where a write about one of these steps goes.
 *
 * Returns `null` when there is no checklist to speak of, otherwise a descriptor naming the
 * routes: `{kind: 'block', blockId}` for a task, `{kind: 'occurrence', routineId, day}` for a
 * day of a routine, `{kind: 'routine', routineId, day: null}` for the rule itself.
 *
 * A rule has no day, so nothing about it can be ticked: its steps are definitions, and the tick
 * belongs to a morning. That is what `tickable` says, and the editor draws no box when it is
 * false rather than drawing one that writes nothing.
 */
export function whereSteps(subject) {
  if (!subject) return null
  if (subject.kind === 'routine') {
    const rule = subject.routine
    if (!rule) return null
    return { kind: 'routine', routineId: rule.id, day: null, tickable: false }
  }
  const block = subject.block
  if (!block) return null
  if (isOccurrence(block)) {
    return {
      kind: 'occurrence',
      routineId: block.routine_id,
      day: block.occurrence_day ?? block.day,
      tickable: true,
    }
  }
  return { kind: 'block', blockId: block.id, day: block.day ?? null, tickable: true }
}
