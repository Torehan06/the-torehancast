import { DISTRICT_BY_KEY } from '../data/districts'
import type { ParsedHouse } from '../data/parse'
import { STATE_BY_CODE } from '../data/states'
import { RaceCard } from './RacePanel'

interface Props {
  districtKey: string
  house: ParsedHouse | null
  onClose: () => void
}

/** One House district, with source coverage independent of the current snapshot. */
export function DistrictPanel({ districtKey, house, onClose }: Props) {
  const district = DISTRICT_BY_KEY.get(districtKey)
  if (!district) return null
  return (
    <RaceCard
      raceId={district.raceId}
      title={district.label}
      subtitle={`${district.name}, U.S. House`}
      place={STATE_BY_CODE.get(district.state)?.name ?? district.state}
      race={house?.races.get(district.raceId)}
      invalid={house?.invalid.includes(district.raceId) ?? false}
      generatedAt={house?.generatedAt ?? null}
      onClose={onClose}
    />
  )
}
