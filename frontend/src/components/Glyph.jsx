/** The handful of UI glyphs the app needs, inline: no icon dependency, and they
 *  inherit currentColor so the selected tab can invert them. */
const PATHS = {
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  sunrise: <><path d="M12 4v3" /><path d="M6 13a6 6 0 0 1 12 0" /><path d="M3 17h18" /><path d="M5 20h14" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" /></>,
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />,
  check: <path d="M4 12.5l5 5L20 6.5" />,
  calendar: <><rect x="3.5" y="5" width="17" height="15" rx="2.5" /><path d="M3.5 10h17M8 3.5v3M16 3.5v3" /></>,
  link: <><path d="M10 14a4 4 0 0 1 0-5.7l1.4-1.4a4 4 0 0 1 5.7 5.7l-.8.8" /><path d="M14 10a4 4 0 0 1 0 5.7l-1.4 1.4A4 4 0 0 1 6.9 11.4l.8-.8" /></>,
  // Two arrows going round: the mark for "this comes back", on the rows of a routine's day.
  repeat: <><path d="M4.5 9.5A7 7 0 0 1 11 4h5.5" /><path d="M14 1.5 16.5 4 14 6.5" /><path d="M19.5 14.5A7 7 0 0 1 13 20H7.5" /><path d="M10 22.5 7.5 20 10 17.5" /></>,
}

export default function Glyph({ name }) {
  return (
    <svg
      className="glyph"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}
