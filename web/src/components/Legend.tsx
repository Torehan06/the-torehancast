/** The map key. Colour shows who leads; the number is always in the list and panel. */
export function Legend() {
  const items: [string, string][] = [
    ['lead-D strength-strong', 'Democrat ≥95% to win'],
    ['lead-D strength-medium', 'Democrat 75–95%'],
    ['lead-D strength-light', 'Democrat favoured <75%, or leads in votes (no forecast)'],
    ['lead-R strength-strong', 'Republican ≥95% to win'],
    ['lead-R strength-medium', 'Republican 75–95%'],
    ['lead-R strength-light', 'Republican favoured <75%, or leads in votes (no forecast)'],
    ['lead-other strength-medium', 'Other candidate leads'],
    ['state--waiting', 'Senate race, no votes reported'],
    ['state--neutral', 'No Senate race in 2026'],
  ]
  return (
    <ul className="legend" aria-label="Map key">
      {items.map(([cls, text]) => (
        <li key={cls}>
          <span className={`swatch ${cls}`} aria-hidden="true" />
          {text}
        </li>
      ))}
    </ul>
  )
}
