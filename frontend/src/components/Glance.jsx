import { glanceAt } from '../glance'

/** The one-line answer to "what am I supposed to be doing", at the top of the plan.
 *
 *  Only today has a now. On any other day the same sentence would be a claim about an hour that
 *  has not happened yet, so the line is absent there rather than wrong — and sundial is a planner
 *  you are allowed to look ahead in without being told what you are doing on Thursday at 3pm.
 *
 *  It renders nothing when there is nothing to say (see glanceAt), which means the plan is
 *  unchanged for a day with no timed blocks: no empty strip, no "nothing scheduled".
 */
export default function Glance({ blocks, day, today, nowMin }) {
  if (day !== today) return null

  const seen = glanceAt(blocks, nowMin)
  if (!seen) return null

  return (
    <div className={`glance is-${seen.kind}`}>
      <span className="glance-lead">{seen.kind === 'now' ? 'Now' : 'Next'}</span>
      <p className="glance-line">
        <span className="glance-title">{seen.title}</span>
        <span className="glance-meta">
          {seen.when}
          {' · '}
          {seen.left}
        </span>
      </p>
    </div>
  )
}
