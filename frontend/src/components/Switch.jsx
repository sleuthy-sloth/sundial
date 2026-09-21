/**
 * A switch: the one control here that says a state by where a thing sits rather than by a word.
 *
 * The mechanics are borrowed, the care around them is not. Switches are the single most
 * copy-pasted component on the open web, and almost every copy of one makes the same two
 * mistakes this avoids:
 *
 * The input is a real checkbox and stays focusable. What hides it is `opacity: 0` over a
 * full-size box, never `display: none` — a `display: none` input is out of the tab order, so
 * the control becomes unreachable by keyboard and silent to a screen reader. Plenty of the
 * switches worth looking at do exactly that.
 *
 * The focus ring is drawn by the track, because an invisible input has nowhere to draw one.
 * It is the same 2px solar mark at the same 2px offset every other control gets: the ring is
 * the one thing in this app that is never special-cased, and a control that opted out of it
 * would be the only place a keyboard user could lose their place.
 *
 * `role="switch"` is what makes a screen reader say "on" rather than "checked", which is the
 * word this control is actually about.
 */
export default function Switch({
  checked,
  onChange,
  label,
  disabled = false,
  className = '',
}) {
  return (
    <label className={className ? `switch ${className}` : 'switch'}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-knob" aria-hidden="true" />
    </label>
  )
}
