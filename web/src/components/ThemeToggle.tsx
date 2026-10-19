import { useTheme } from '../hooks/useTheme'

/** A ballot-oval switch: the knob sits left for light, right for dark. */
export function ThemeToggle() {
  const [theme, toggle] = useTheme()
  return (
    <button type="button" className="theme-toggle" aria-pressed={theme === 'dark'} onClick={toggle}>
      <span className="theme-toggle__track" aria-hidden="true">
        <span className="theme-toggle__knob" />
      </span>
      <span className="theme-toggle__label">Dark mode</span>
    </button>
  )
}
