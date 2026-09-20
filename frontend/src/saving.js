/** The pieces that make editing survive a slow network.
 *
 * Each one exists because of a specific failure: a PATCH answered out of order puts the
 * older value back, a day load answered after you have navigated away paints the day you
 * left, and a keystroke that reaches the server on its own is a request per letter.
 */

/** Writes for one block go out one at a time, in the order they were asked for.
 *
 * A failed write does not wedge the queue — the next one still runs — but the caller
 * still gets the rejection, because whoever asked for the write is the one who has to
 * say so on screen.
 */
export function createWriteQueue() {
  const chains = new Map()
  return {
    run(key, task) {
      const previous = chains.get(key) || Promise.resolve()
      const next = previous.then(task, task)
      // Keep the chain alive whatever the task did; the caller keeps the rejection.
      chains.set(key, next.then(() => {}, () => {}))
      return next
    },
  }
}

/** Marks the newest of several loads, so a slow one can be recognised as stale.
 *
 * Navigating away does not cancel the request already in flight. Without a ticket its
 * answer arrives later and paints the day you left under the heading of the day you are
 * looking at — which is worse than the wait, because it looks correct.
 */
export function createLatest() {
  let issued = 0
  let current = 0
  return {
    begin() {
      issued += 1
      current = issued
      return issued
    },
    isCurrent(ticket) {
      return ticket === current
    },
  }
}

/** Run once, after things have stopped happening for `wait` milliseconds. */
export function debounce(fn, wait) {
  let timer = null
  let last = null

  const fire = () => {
    timer = null
    const args = last
    last = null
    if (args) fn(...args)
  }

  const wrapped = (...args) => {
    last = args
    if (timer) clearTimeout(timer)
    timer = setTimeout(fire, wait)
  }

  /** Send whatever is waiting, now — leaving a field or closing the editor. */
  wrapped.flush = () => {
    if (timer) {
      clearTimeout(timer)
      fire()
    }
  }
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer)
    timer = null
    last = null
  }
  wrapped.pending = () => timer !== null
  return wrapped
}
