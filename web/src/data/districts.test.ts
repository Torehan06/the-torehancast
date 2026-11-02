import { describe, expect, it } from 'vitest'
import { DISTRICT_BY_KEY, DISTRICTS, HOUSE_RACE_IDS, districtName, tileInDirection, type Direction } from './districts'

describe('the 435 tiles', () => {
  it('map one to one onto the canonical race IDs', () => {
    expect(DISTRICTS).toHaveLength(435)
    expect(DISTRICTS.map((d) => d.raceId).sort()).toEqual([...HOUSE_RACE_IDS].sort())
    expect(DISTRICT_BY_KEY.get('NC-01')).toMatchObject({ raceId: '2026-NC-H01', label: 'NC-1', number: 1 })
    expect(DISTRICT_BY_KEY.get('AK-AL')).toMatchObject({ raceId: '2026-AK-HAL', label: 'AK-AL', number: 1 })
    expect(DISTRICT_BY_KEY.get('CA-52')).toMatchObject({ raceId: '2026-CA-H52', label: 'CA-52', number: 52 })
  })

  it('are named for people', () => {
    expect(districtName('NC', 1)).toBe("North Carolina's 1st District")
    expect(districtName('CA', 12)).toBe("California's 12th District")
    expect(districtName('CA', 22)).toBe("California's 22nd District")
    expect(districtName('TX', 33)).toBe("Texas's 33rd District")
    expect(districtName('AK', 1)).toBe("Alaska's at-large district")
  })
})

describe('arrow keys on the tile map', () => {
  it('reach every tile from the first one', () => {
    const seen = new Set([DISTRICTS[0].key])
    const queue = [DISTRICTS[0]]
    while (queue.length) {
      const from = queue.pop()!
      for (const dir of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'] as Direction[]) {
        const next = tileInDirection(from, dir)
        if (next && !seen.has(next.key)) {
          seen.add(next.key)
          queue.push(next)
        }
      }
    }
    expect(seen.size).toBe(435)
  })

  it('always move the way the key says, and stop at the edge', () => {
    for (const d of DISTRICTS) {
      const right = tileInDirection(d, 'ArrowRight')
      const down = tileInDirection(d, 'ArrowDown')
      if (right) expect(right.x).toBeGreaterThan(d.x)
      if (down) expect(down.y).toBeGreaterThan(d.y)
    }
    const leftmost = Math.min(...DISTRICTS.map((d) => d.x))
    expect(tileInDirection(DISTRICTS.find((d) => d.x === leftmost)!, 'ArrowLeft')).toBeNull()
  })
})
