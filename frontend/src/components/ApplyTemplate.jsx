import { useState } from 'react'

import { canApply, describeTemplate } from '../templates'

/**
 * "Apply template", and then the one you want — the two taps the plan asks for in Today.
 *
 * A button that opens the list rather than a dropdown sitting open on the page: a template is
 * something you reach for occasionally, and six controls above the day would make the occasional
 * thing look like the main one. Closed, this is a sentence and a button.
 *
 * Applying is additive and the note says what it did, in the app's own words for a block. It does
 * not say what the day now holds: the day below it is already saying that.
 *
 * A template with nothing in it is offered as a disabled row rather than hidden — the list under
 * You is where you fill it in, and a name that vanished from here would look like a bug.
 */
export default function ApplyTemplate({ templates, note, onApply }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="template-apply">
      <div className="template-apply-row">
        <button
          type="button"
          className="template-apply-open"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          Apply template
        </button>
        {note && (
          <p className="note template-note" role="status">{note}</p>
        )}
      </div>

      {open && (
        templates.length === 0 ? (
          <p className="note">
            No templates yet. Write one under You — a workday, a weekend reset, an evening —
            and it can be put on any day without repeating on its own.
          </p>
        ) : (
          <ul className="template-picks">
            {templates.map((template) => (
              <li key={template.id}>
                <button
                  type="button"
                  className="template-pick"
                  data-template-id={template.id}
                  disabled={!canApply(template)}
                  onClick={() => {
                    setOpen(false)
                    onApply(template.id)
                  }}
                >
                  <span className="template-pick-name">{template.name}</span>
                  <span className="template-pick-what">{describeTemplate(template)}</span>
                </button>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  )
}
