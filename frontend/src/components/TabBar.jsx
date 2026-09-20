import Glyph from './Glyph'

export default function TabBar({ view, onPick }) {
  return (
    <nav className="tabbar" role="tablist" aria-label="Views">
      <button
        className={`tab${view === 'todo' ? ' on' : ''}`}
        role="tab"
        aria-selected={view === 'todo'}
        onClick={() => onPick('todo')}
        title="To-do"
      >
        <Glyph name="check" />
      </button>
      <button
        className={`tab${view === 'calendar' ? ' on' : ''}`}
        role="tab"
        aria-selected={view === 'calendar'}
        onClick={() => onPick('calendar')}
        title="Calendar"
      >
        <Glyph name="calendar" />
      </button>
    </nav>
  )
}
