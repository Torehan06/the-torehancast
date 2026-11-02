import { describe, expect, it } from 'vitest'
import { APPORTIONMENT, districtKeys } from '../geo/apportionment'
import houseTiles from './houseTiles.json'

const { tiles } = houseTiles

function fourConnected(cells: { x: number; y: number }[]): boolean {
  const all = new Set(cells.map((c) => `${c.x},${c.y}`))
  const seen = new Set([`${cells[0].x},${cells[0].y}`])
  const queue = [cells[0]]
  while (queue.length) {
    const { x, y } = queue.pop()!
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const k = `${x + dx},${y + dy}`
      if (all.has(k) && !seen.has(k)) {
        seen.add(k)
        queue.push({ x: x + dx, y: y + dy })
      }
    }
  }
  return seen.size === all.size
}

describe('houseTiles.json', () => {
  it('has one tile per district, keyed by the 2020 apportionment', () => {
    expect(tiles).toHaveLength(435)
    expect(tiles.map((t) => t.id).sort()).toEqual(districtKeys())
    for (const t of tiles) expect(t.id.slice(0, 2)).toBe(t.state)
  })

  it('puts every tile in its own cell, inside the grid', () => {
    expect(new Set(tiles.map((t) => `${t.x},${t.y}`)).size).toBe(435)
    for (const t of tiles) {
      expect(t.x).toBeGreaterThanOrEqual(0)
      expect(t.y).toBeGreaterThanOrEqual(0)
      expect(t.x).toBeLessThan(houseTiles.width)
      expect(t.y).toBeLessThan(houseTiles.height)
    }
  })

  it.each(Object.keys(APPORTIONMENT))('keeps %s in one 4-connected block', (state) => {
    expect(fourConnected(tiles.filter((t) => t.state === state))).toBe(true)
  })
})
