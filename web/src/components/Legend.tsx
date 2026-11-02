/** The map key. Colour shows who leads; the number is always in the list and panel. */
const TIERS: [string, string][] = [
  ['strong', '95% or more'],
  ['medium', '75–95%'],
  ['light', 'under 75%'],
]

export function Legend({ chamber = 'senate' }: { chamber?: 'senate' | 'house' }) {
  return (
    <div className="legend" aria-label="Map key" role="group">
      {(['D', 'R'] as const).map((side) => (
        <div className="legend__row" key={side}>
          <span className="legend__party">{side === 'D' ? 'Democrat' : 'Republican'} favoured</span>
          <ul>
            {TIERS.map(([strength, text]) => (
              <li key={strength}>
                <span className={`swatch lead-${side} strength-${strength}`} aria-hidden="true" />
                {text}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <ul className="legend__other">
        <li>
          <span className="swatch lead-other strength-medium" aria-hidden="true" />
          Another candidate leads
        </li>
        <li>
          <span className="swatch state--waiting" aria-hidden="true" />
          No votes yet
        </li>
        {chamber === 'senate' && (
          <li>
            <span className="swatch state--neutral" aria-hidden="true" />
            No Senate race this year
          </li>
        )}
      </ul>
      <p className="legend__note">In races we don’t forecast, the lightest shade marks who leads the count.</p>
      {chamber === 'house' && (
        <p className="legend__note">
          Each square is one district, placed roughly where it is.{' '}
          <span className="legend__numbers">
            A square’s number is its district number, not a result; a state’s code marks its 1st district or its only one.
          </span>
          <span className="legend__small">The squares are small on this screen: browse by state below to pick a district.</span>
        </p>
      )}
    </div>
  )
}
