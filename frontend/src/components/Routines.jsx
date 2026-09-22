import { hhmm } from '../time'

/** The routines you have, where the app's own settings live.
 *
 * A routine is only reachable from one of its days otherwise, and a day you have skipped is a
 * day with nothing on it to tap — so without this list a rule you turned off would be a rule you
 * could not turn back on. That is the whole reason it is here; the count is not the point.
 *
 * Nothing here is a judgement: a routine that is off says "off", which is what it is.
 */
export default function Routines({ routines, onOpen }) {
  return (
    <>
      <h2>Routines</h2>

      {routines.length === 0 ? (
        <p className="note">
          Nothing repeats yet. Open a block and set it to repeat, and it is listed here.
        </p>
      ) : (
        <ul className="routine-list">
          {routines.map((routine) => (
            <li key={routine.id} className="routine-row">
              <button
                type="button"
                className="routine-open"
                data-routine-id={routine.id}
                onClick={() => onOpen(routine.id)}
              >
                <span className="routine-title">
                  {routine.icon && <span className="block-icon">{routine.icon}</span>}
                  {routine.title}
                </span>
                <span className="routine-when">
                  {routine.summary} · {hhmm(routine.start_min)}–{hhmm(routine.start_min + routine.duration_min)}
                  {routine.enabled ? '' : ' · off'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="note">
        A routine is a rule rather than a row for every day it lands on: the only days written
        down are the ones you changed.
      </p>
    </>
  )
}
