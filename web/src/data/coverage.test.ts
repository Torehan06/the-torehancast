import { describe, expect, it } from 'vitest'
import { trackedRaceIds, rankedChoiceRaceIds } from 'virtual:coverage'
import { HOUSE_RACE_IDS, APPORTIONMENT, houseRaceId } from './districts'
import { SENATE_RACES_2026, senateRaceId } from './states'
import { isNotTracked } from './coverage'

const states = ['AK', 'FL', 'GA', 'IA', 'MN', 'NC', 'NE', 'OH', 'SC']

describe('configured coverage', () => {
  it('contains exactly 9 Senate and 94 House races, independently enumerated', () => {
    const expected = states.flatMap((state) => [senateRaceId(state), ...Array.from({ length: APPORTIONMENT[state] }, (_, n) => houseRaceId(state, n + 1))])
    expect([...trackedRaceIds].sort()).toEqual(expected.sort())
    expect(trackedRaceIds).toHaveLength(103)
    expect(HOUSE_RACE_IDS.filter((id) => !trackedRaceIds.includes(id))).toHaveLength(341)
    expect(SENATE_RACES_2026.filter(({ state }) => !trackedRaceIds.includes(senateRaceId(state.code)))).toHaveLength(26)
    expect([...rankedChoiceRaceIds].sort()).toEqual(['2026-AK-HAL', '2026-AK-SEN'])
  })

  it.each(['2026-GA-SEN', '2026-GA-H14', '2026-AK-SEN', '2026-AK-HAL', '2026-FL-H13', '2026-OH-H03', '2026-MN-H08'])('%s stays tracked with no published entry', (id) => {
    expect(isNotTracked(id, undefined)).toBe(false)
  })

  it.each(['2026-TX-SEN', '2026-KS-SEN', '2026-MI-SEN', '2026-ME-SEN', '2026-TX-H01', '2026-ME-H02', '2026-WY-HAL'])('%s has no configured feed', (id) => {
    expect(isNotTracked(id, undefined)).toBe(true)
  })
})
