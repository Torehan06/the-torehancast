import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import App from './App'

it('renders the masthead', () => {
  render(<App />)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('The TörehanCast')
})

it('counts the other Senate races after dropped seats move out of the swing grid', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: '9 swing seats' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Other 26 races' })).toBeInTheDocument()
  expect(within(screen.getByRole('list', { name: 'Other 2026 Senate races' })).getAllByRole('button')).toHaveLength(26)
})
