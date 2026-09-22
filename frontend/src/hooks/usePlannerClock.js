/** The minute the app thinks it is.
 *
 *  One timer, ticking every thirty seconds, so the timeline's now-line and the glance's
 *  countdown move on their own without every component that reads the clock keeping one.
 */

import { useEffect, useState } from 'react'
import { minsNow } from '../time'

export function usePlannerClock() {
  const [nowMin, setNowMin] = useState(minsNow)

  useEffect(() => {
    const t = setInterval(() => setNowMin(minsNow()), 30_000)
    return () => clearInterval(t)
  }, [])

  return nowMin
}
