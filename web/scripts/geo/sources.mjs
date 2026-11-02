/**
 * Where each state's Nov 2026 congressional districts come from, and loaders that turn a
 * raw download into WGS84 GeoJSON features keyed 'NC-01' / 'AK-AL'.
 *
 * Raw files live in the gitignored data/archives/geo/<dir>/ (see docs/geo-sources.md for
 * URLs, dates and sha256). States not in REDRAWN keep their 119th-Congress lines and come
 * from the Census CD119 cartographic boundary file.
 */

import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { geoArea } from 'd3-geo'
import mapshaper from 'mapshaper'

export const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
export const ARCHIVE = process.env.GEO_ARCHIVE ?? resolve(WEB, '../data/archives/geo')

// 2020-census apportionment, mirrored from src/torehancast/districts.py (claude/w2-registry).
export const APPORTIONMENT = {
  AL: 7, AK: 1, AZ: 9, AR: 4, CA: 52, CO: 8, CT: 5, DE: 1, FL: 28, GA: 14,
  HI: 2, ID: 2, IL: 17, IN: 9, IA: 4, KS: 4, KY: 6, LA: 6, ME: 2, MD: 8,
  MA: 9, MI: 13, MN: 8, MS: 4, MO: 8, MT: 2, NE: 3, NV: 4, NH: 2, NJ: 12,
  NM: 3, NY: 26, NC: 14, ND: 1, OH: 15, OK: 5, OR: 6, PA: 17, RI: 2, SC: 7,
  SD: 1, TN: 9, TX: 38, UT: 4, VT: 1, VA: 11, WA: 10, WV: 2, WI: 8, WY: 1,
}

export const FIPS = {
  AL: '01', AK: '02', AZ: '04', AR: '05', CA: '06', CO: '08', CT: '09', DE: '10', FL: '12', GA: '13',
  HI: '15', ID: '16', IL: '17', IN: '18', IA: '19', KS: '20', KY: '21', LA: '22', ME: '23', MD: '24',
  MA: '25', MI: '26', MN: '27', MS: '28', MO: '29', MT: '30', NE: '31', NV: '32', NH: '33', NJ: '34',
  NM: '35', NY: '36', NC: '37', ND: '38', OH: '39', OK: '40', OR: '41', PA: '42', RI: '44', SC: '45',
  SD: '46', TN: '47', TX: '48', UT: '49', VT: '50', VA: '51', WA: '53', WV: '54', WI: '55', WY: '56',
}
export const STATE_BY_FIPS = Object.fromEntries(Object.entries(FIPS).map(([s, f]) => [f, s]))

export const districtId = (state, n) =>
  APPORTIONMENT[state] === 1 ? `${state}-AL` : `${state}-${String(n).padStart(2, '0')}`

export const CD119 = {
  dir: 'us-cd119',
  file: 'cb_2025_us_cd119_500k.zip',
  sha256: '8e804518d333d67e24e25c61767c6a7c78fd0a0852179e8cc19c36fd66011010',
}

/**
 * Redrawn for Nov 2026. `file` is the archived download; `field` holds the district number.
 * A state whose file isn't archived yet is reported missing and stops the district build.
 */
export const REDRAWN = {
  TX: { dir: 'TX', plan: 'PLANC2333 (HB 4, 2nd C.S. 2025)', blocked: 'data.capitol.texas.gov answers 403 from this network' },
  CA: {
    dir: 'CA', file: 'ab604_districts_shapefile.zip', field: 'DISTRICT', plan: 'AB 604 (Prop 50)',
    sha256: '0adf00848210b81abb38b62f24f05a854dc1f8dcfec44c8af5a4eb847c481f74',
  },
  NC: { dir: 'NC', plan: 'SL 2025-95 (SB 249)', blocked: 'ncleg.gov answers 403 from this network' },
  OH: { dir: 'OH', plan: 'Ohio Redistricting Commission plan of Oct 31, 2025', blocked: 'redistricting.ohio.gov times out from this network' },
  UT: {
    dir: 'UT', file: 'political_us_congress_districts_2026_to_2032.zip', field: 'DISTRICT',
    plan: 'Court-ordered Map 1 (Third District Court, Nov 10, 2025)',
    sha256: 'bc3bbe19da6c0b425e0dbd584ee6eb326d7cabe96dd50c1bd0b64b6f43f8e34b',
  },
  FL: {
    dir: 'FL', file: 'EOGPCRP2026.zip', field: 'DISTRICT', plan: 'EOGPCRP2026 (HB 1-D, ch. 2026-229)',
    sha256: '253cfc70414929eeccd29f4c559746e480fb3d2b4e94c2fd02d3175a9923a789',
  },
  TN: { dir: 'TN', plan: '2026 extraordinary session plan (signed May 7, 2026)', blocked: 'capitol.tn.gov refuses connections and sos.tn.gov answers 403 from this network' },
  AL: { dir: 'AL', plan: 'Livingston Congressional Plan 3-2023', blocked: 'only a legal-description PDF is reachable, and its text is clipped (a Jefferson County tract list is cut mid-line); needs a shapefile or block assignment file' },
  LA: { dir: 'LA', plan: 'Act 2 of 2026 (SB 121)', blocked: 'legis.la.gov does not resolve from this network' },
}

export function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

/** Archived path for a source, after checking its hash; null if it isn't archived. */
export function archived(source) {
  if (!source.file) return null
  const path = resolve(ARCHIVE, source.dir, source.file)
  if (!existsSync(path)) return null
  const got = sha256(path)
  if (got !== source.sha256) throw new Error(`${path}: sha256 ${got}, expected ${source.sha256}`)
  return path
}

async function readFeatures(path, commands) {
  const out = await mapshaper.applyCommands(
    `-i "${path}" ${commands} -proj wgs84 -o out.json format=geojson precision=0.000001`,
  )
  return JSON.parse(out['out.json'].toString()).features
}

// mapshaper writes RFC 7946 rings (exterior counter-clockwise); d3-geo reads the opposite.
function rewind(geometry) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  for (const rings of polygons) for (const ring of rings) ring.reverse()
  return geometry
}

function keyed(state, n, feature, source) {
  const f = {
    type: 'Feature',
    id: districtId(state, n),
    properties: { state, district: n, source },
    geometry: rewind(feature.geometry),
  }
  if (geoArea(f) > 2 * Math.PI) throw new Error(`${f.id}: ring winding still inverted after rewind`)
  return f
}

/** CD119 features for the given states (all non-redrawn states by default). */
export async function loadCd119(states) {
  const path = archived(CD119)
  if (!path) throw new Error(`missing ${resolve(ARCHIVE, CD119.dir, CD119.file)}`)
  const fips = new Set(states.map((s) => FIPS[s]))
  const raw = await readFeatures(path, '')
  return raw
    .filter((f) => fips.has(f.properties.STATEFP))
    .map((f) => {
      const state = STATE_BY_FIPS[f.properties.STATEFP]
      const n = f.properties.CD119FP === '00' ? 1 : Number(f.properties.CD119FP)
      return keyed(state, n, f, 'cd119')
    })
}

/** One redrawn state's features, or null if its file isn't archived. */
export async function loadRedrawn(state) {
  const source = REDRAWN[state]
  const path = archived(source)
  if (!path) return null
  const raw = await readFeatures(path, `-dissolve ${source.field} copy-fields=${source.field}`)
  return raw.map((f) => keyed(state, Number(f.properties[source.field]), f, state))
}

/**
 * Every district we can build now. `missing` lists redrawn states whose official file
 * isn't archived; with `fallback`, those states use CD119 shapes (tiles only — never the map).
 */
export async function loadAll({ fallback = false } = {}) {
  const features = []
  const missing = []
  for (const state of Object.keys(REDRAWN)) {
    const got = await loadRedrawn(state)
    if (got) features.push(...got)
    else missing.push(state)
  }
  const cd119States = Object.keys(APPORTIONMENT).filter(
    (s) => !(s in REDRAWN) || (fallback && missing.includes(s)),
  )
  features.push(...(await loadCd119(cd119States)))
  return { features, missing }
}
