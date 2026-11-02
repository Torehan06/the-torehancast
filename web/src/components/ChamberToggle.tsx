import type { View } from '../data/route'

const CHAMBERS: [View, string][] = [
  ['senate', 'Senate'],
  ['house', 'House'],
]

/** Senate | House, marked like a ballot: the chosen one has its oval filled in. */
export function ChamberToggle({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return (
    <div className="chamber" role="group" aria-label="Chamber">
      {CHAMBERS.map(([value, name]) => (
        <button
          key={value}
          type="button"
          className="chamber__option"
          aria-pressed={view === value}
          onClick={() => {
            if (view !== value) onChange(value)
          }}
        >
          <span className="chamber__oval" aria-hidden="true" />
          {name}
        </button>
      ))}
    </div>
  )
}
