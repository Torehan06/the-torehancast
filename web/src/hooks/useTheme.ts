import { useCallback, useState } from 'react'

export type Theme = 'dark' | 'light'

/**
 * The page theme lives on <html data-theme>. index.html sets it before first
 * paint (dark unless the visitor chose light); this hook flips it and saves the
 * choice. Storage can be unavailable (private mode), so failures are ignored.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === 'light' ? 'light' : 'dark',
  )
  const toggle = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('theme', next)
    } catch {
      // The toggle still works for this visit.
    }
    setTheme(next)
  }, [theme])
  return [theme, toggle]
}
