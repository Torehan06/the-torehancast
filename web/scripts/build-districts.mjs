/**
 * Builds web/src/geo/cd2026.topo.json: the 435 congressional districts for Nov 3, 2026,
 * pre-projected like us-atlas (geoAlbersUsa().scale(1300).translate([487.5, 305])) so they
 * line up with us-atlas/states-albers-10m.json. One TopoJSON object, `districts`, each
 * geometry keyed 'NC-01' (at-large seats 'AK-AL') with properties { state }.
 *
 * Sources: scripts/geo/sources.mjs and docs/geo-sources.md. Each state's districts are
 * clipped to that state's us-atlas outline, so coasts and state lines match the state layer.
 *
 * Refuses to write while any redrawn state's official file is missing. --provisional OUT
 * writes a CD119 stand-in for those states to OUT instead (pipeline checks only; never ship it).
 *
 *   node scripts/build-districts.mjs [--provisional out.json]
 */

import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { geoAlbersUsa } from 'd3-geo'
import { geoProject } from 'd3-geo-projection'
import mapshaper from 'mapshaper'
import { feature } from 'topojson-client'
import { FIPS, REDRAWN, STATE_BY_FIPS, WEB, loadAll } from './geo/sources.mjs'

const OUT = resolve(WEB, 'src/geo/cd2026.topo.json')
const MAX_BYTES = 700 * 1024
const projection = geoAlbersUsa().scale(1300).translate([487.5, 305])

// mapshaper guesses lat/long for small coordinate ranges, which would turn a planar clip of
// one state's pixels into a spherical one. Shifting far out of range keeps every run planar.
const SHIFT = 10000
const shift = (fc, d) => {
  const move = (c) => (typeof c[0] === 'number' ? [c[0] + d, c[1] + d] : c.map(move))
  return { ...fc, features: fc.features.map((f) => ({ ...f, geometry: f.geometry && { ...f.geometry, coordinates: move(f.geometry.coordinates) } })) }
}

async function mapshaperJson(commands, inputs) {
  const out = await mapshaper.applyCommands(commands, inputs)
  return JSON.parse(out['out.json'].toString())
}

function stateOutlines() {
  const atlas = JSON.parse(readFileSync(resolve(WEB, 'node_modules/us-atlas/states-albers-10m.json'), 'utf8'))
  const outlines = {}
  for (const f of feature(atlas, atlas.objects.states).features) {
    const state = STATE_BY_FIPS[f.id]
    if (state) outlines[state] = { ...f, properties: { state } }
  }
  return outlines
}

const collection = (features) => ({ type: 'FeatureCollection', features })

function vertices(geometry) {
  const out = []
  const walk = (c) => (typeof c[0] === 'number' ? out.push(c) : c.forEach(walk))
  walk(geometry.coordinates)
  return out
}

/**
 * Fit one state's districts to its us-atlas outline: clip off whatever falls outside, then
 * give each piece of the outline no district covers (bays the 1:10m outline counts as land,
 * coastline differences) to the district it shares the most boundary with.
 */
async function fitToState(districts, outline) {
  const state = shift(collection([outline]), SHIFT)
  const clipped = await mapshaperJson('-i d.json -clip s.json -o out.json format=geojson', {
    'd.json': shift(collection(districts), SHIFT),
    's.json': state,
  })
  const gaps = await mapshaperJson('-i s.json -erase d.json -explode -o out.json format=geojson', {
    's.json': state,
    'd.json': clipped,
  })
  const key = (c) => `${c[0].toFixed(2)},${c[1].toFixed(2)}`
  const owners = new Map()
  for (const d of clipped.features) for (const v of vertices(d.geometry)) owners.set(key(v), d.properties.id)
  const fill = []
  for (const gap of gaps.features ?? []) {
    if (!gap.geometry) continue
    const votes = new Map()
    for (const v of vertices(gap.geometry)) {
      const id = owners.get(key(v))
      if (id) votes.set(id, (votes.get(id) ?? 0) + 1)
    }
    const [id] = [...votes].sort((a, b) => b[1] - a[1])[0] ?? []
    if (!id) continue // an island no district touches; too small to matter for coverage
    fill.push({ ...gap, properties: { id, state: outline.properties.state } })
  }
  const merged = fill.length
    ? await mapshaperJson('-i m.json -dissolve2 id copy-fields=state -o out.json format=geojson', {
        'm.json': collection([...clipped.features, ...fill]),
      })
    : clipped
  return shift(merged, -SHIFT).features
}

async function main() {
  const i = process.argv.indexOf('--provisional')
  const provisional = i > 0 ? resolve(process.argv[i + 1]) : null

  const { features, missing } = await loadAll({ fallback: Boolean(provisional) })
  if (missing.length && !provisional) {
    console.error('Not writing cd2026.topo.json: official 2026 plans missing for ' + missing.join(', '))
    for (const s of missing) console.error(`  ${s} ${REDRAWN[s].plan}: ${REDRAWN[s].blocked ?? 'not archived'}`)
    console.error(`Archive each file under data/archives/geo/<ST>/ and add it to scripts/geo/sources.mjs.`)
    process.exit(1)
  }

  const outlines = stateOutlines()
  const clipped = []
  for (const state of Object.keys(FIPS)) {
    const projected = features
      .filter((f) => f.properties.state === state)
      .map((f) => ({ ...geoProject(f, projection), id: f.id, properties: { id: f.id, state } }))
    clipped.push(...(await fitToState(projected, outlines[state])))
  }

  // One pass over every district so shared borders simplify together and become shared arcs.
  const topo = await mapshaper.applyCommands(
    '-i all.json name=districts -simplify planar visvalingam interval=0.35 keep-shapes ' +
      '-o out.json format=topojson id-field=id quantization=50000 precision=0.01',
    { 'all.json': shift({ type: 'FeatureCollection', features: clipped }, SHIFT) },
  )
  // Undo the shift inside the TopoJSON transform, so coordinates match states-albers-10m.
  const out = JSON.parse(topo['out.json'].toString())
  out.transform.translate = out.transform.translate.map((t) => t - SHIFT)
  out.bbox = out.bbox?.map((b) => b - SHIFT)
  for (const g of out.objects.districts.geometries) delete g.properties.id
  if (missing.length) out.provisional = missing

  const target = provisional ?? OUT
  writeFileSync(target, JSON.stringify(out))
  const bytes = statSync(target).size
  console.log(`${target}: ${out.objects.districts.geometries.length} districts, ${(bytes / 1024).toFixed(0)} KB` +
    (missing.length ? ` (PROVISIONAL: CD119 lines for ${missing.join(', ')})` : ''))
  if (bytes > MAX_BYTES) {
    console.error(`over the ${MAX_BYTES / 1024} KB budget`)
    process.exit(1)
  }
}

await main()
