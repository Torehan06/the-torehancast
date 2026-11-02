import { describe, expect, it } from 'vitest'
import { parseRoute, routeHash } from './route'

describe('hash routes', () => {
  it.each([
    ['', { view: 'senate', selected: null }],
    ['#GA', { view: 'senate', selected: 'GA' }],
    ['#ga', { view: 'senate', selected: 'GA' }],
    ['#AL', { view: 'senate', selected: 'AL' }], // Alabama's Senate race, not an at-large seat
    ['#CA', { view: 'senate', selected: null }], // no Senate race
    ['#house', { view: 'house', selected: null }],
    ['#HOUSE', { view: 'house', selected: null }],
    ['#NC-01', { view: 'house', selected: 'NC-01' }],
    ['#nc-01', { view: 'house', selected: 'NC-01' }],
    ['#AK-AL', { view: 'house', selected: 'AK-AL' }],
    ['#NC-99', { view: 'senate', selected: null }], // not a seat
    ['#AK-01', { view: 'senate', selected: null }],
  ])('%s', (hash, route) => {
    expect(parseRoute(hash)).toEqual(route)
  })

  it('round-trips', () => {
    for (const hash of ['GA', 'house', 'NC-01', 'AK-AL']) expect(routeHash(parseRoute(hash))).toBe(hash)
    expect(routeHash({ view: 'senate', selected: null })).toBe('')
  })
})
