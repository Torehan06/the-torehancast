import { existsSync, readFileSync } from 'node:fs'
import { geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import usAtlas from 'us-atlas/states-albers-10m.json'
import { describe, expect, it } from 'vitest'
import { STATE_BY_FIPS } from '../data/states'
import { APPORTIONMENT, districtKeys } from './apportionment'

// CD2026_TOPO points the checks at another build (e.g. a --provisional one).
const file = process.env.CD2026_TOPO ?? new URL('./cd2026.topo.json', import.meta.url).pathname
const built = existsSync(file)

describe.skipIf(!built)('cd2026.topo.json', () => {
  const topo = built ? (JSON.parse(readFileSync(file, 'utf8')) as Topology) : (null as never)
  const districts = built
    ? feature(topo, topo.objects.districts as GeometryCollection<{ state: string }>).features
    : []
  const area = geoPath().area

  it('has exactly 435 districts, keyed by the 2020 apportionment', () => {
    expect(districts).toHaveLength(435)
    expect(districts.map((d) => d.id).sort()).toEqual(districtKeys())
    for (const d of districts) expect(String(d.id).slice(0, 2)).toBe(d.properties.state)
  })

  it('is not a provisional build', () => {
    expect((topo as unknown as { provisional?: string[] }).provisional ?? []).toEqual([])
  })

  it('covers each us-atlas state outline within 1% of its area', () => {
    const atlas = usAtlas as unknown as Topology
    const outlines = feature(atlas, atlas.objects.states as GeometryCollection).features
    const misses: string[] = []
    for (const outline of outlines) {
      const state = STATE_BY_FIPS.get(String(outline.id))?.code
      if (!state || !(state in APPORTIONMENT)) continue
      const target = area(outline)
      const covered = districts.filter((d) => d.properties.state === state).reduce((sum, d) => sum + area(d), 0)
      const error = Math.abs(covered - target) / target
      if (error > 0.01) misses.push(`${state} ${(error * 100).toFixed(2)}%`)
    }
    expect(misses).toEqual([])
  })
})
