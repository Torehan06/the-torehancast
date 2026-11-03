/** Build-only: read public registry metadata, never priors or private inputs. */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from 'yaml'
import { APPORTIONMENT, houseRaceId } from '../src/data/districts'
import { senateRaceId } from '../src/data/states'

interface Feed { status: string; adapter?: string | null; url?: string | null }
interface ConfiguredRace { status: string; ranked_choice: boolean }
interface Source extends Feed {
  same_as?: string
  contests: { office: 'senate' | 'house'; districts?: 'all' | number[] }[]
}

export function readCoverage(directory = resolve(import.meta.dirname, '../../config')) {
  const read = (file: string) => parse(readFileSync(resolve(directory, file), 'utf8'))
  const races = read('races.yaml').races as Record<string, ConfiguredRace>
  const feeds = read('feeds.yaml').feeds as Record<string, Feed>
  const tracked = new Set<string>()
  const rankedChoice = new Set<string>()
  const forecasts = new Set(Object.keys(races).filter((id) => races[id].status !== 'dropped'))
  const hasFeed = (feed: Feed | undefined) => Boolean(feed?.adapter && feed.url)
  for (const [id, feed] of Object.entries(feeds)) {
    if (feed.status !== 'ready' || !forecasts.has(id)) continue
    if (!hasFeed(feed)) throw new Error(`Ready feed lacks a source: ${id}`)
    tracked.add(id)
    if (races[id].ranked_choice) rankedChoice.add(id)
  }
  for (const file of readdirSync(resolve(directory, 'results')).filter((f) => /^[A-Z]{2}\.yaml$/.test(f)).sort()) {
    const state = file.slice(0, 2)
    const sources = read(`results/${file}`).results.sources as Record<string, Source>
    for (const source of Object.values(sources ?? {})) {
      if (source.status !== 'ready') continue
      if (!hasFeed(source.same_as ? feeds[source.same_as] : source)) throw new Error(`Ready results source lacks a feed: ${file}`)
      for (const contest of source.contests) {
        if (contest.office === 'senate') {
          tracked.add(senateRaceId(state))
        } else {
          const numbers = contest.districts === 'all'
            ? Array.from({ length: APPORTIONMENT[state] }, (_, n) => n + 1).filter((n) => !forecasts.has(houseRaceId(state, n)))
            : contest.districts
          if (!numbers) throw new Error(`House source lacks districts: ${file}`)
          for (const n of numbers) tracked.add(houseRaceId(state, n))
        }
      }
    }
  }
  // Explicit allowlist: no other config values can enter the client module.
  return { trackedRaceIds: [...tracked].sort(), rankedChoiceRaceIds: [...rankedChoice].sort() }
}
