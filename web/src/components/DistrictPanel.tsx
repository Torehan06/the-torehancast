import { DISTRICT_BY_KEY } from '../data/districts'
import type { ParsedHouse } from '../data/parse'
import { STATE_BY_CODE } from '../data/states'
import { RaceCard } from './RacePanel'

interface Props {
  districtKey: string
  house: ParsedHouse | null
  onClose: () => void
}

/** One House district. A race absent from house.json (or no file at all) has no votes. */
export function DistrictPanel({ districtKey, house, onClose }: Props) {
  const district = DISTRICT_BY_KEY.get(districtKey)
  if (!district) return null
  return (
    <RaceCard
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
