/**
 * Builds web/src/data/houseTiles.json: our own House tile cartogram (MIT), one square per
 * district, each state a contiguous block.
 *
 * Each state's block is hand-placed below: top-left cell, width in cells, and which side
 * its short row sits on. Districts fill the block by geography: sorted north to south into
 * rows, then west to east within a row, using district centroids from the 2026 shapes
 * (CD119 shapes stand in for redrawn states whose official file isn't archived yet; rerun
 * once it is). ORDER pins a state's cells by hand where centroids read badly.
 *
 *   node scripts/build-tiles.mjs [--preview out.svg]
 */

import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { geoAlbersUsa, geoCentroid } from 'd3-geo'
import { APPORTIONMENT, WEB, districtId, loadAll } from './geo/sources.mjs'

// state: [x, y, width, { short: 'top' | 'bottom', align: 'left' | 'right' | 'center' }]
const LAYOUT = {
  AK: [0, 0, 1],
  HI: [0, 17, 2],
  WA: [0, 1, 5],
  OR: [2, 3, 3],
  CA: [0, 5, 5, { align: 'right' }],
  ID: [5, 2, 1],
  NV: [5, 4, 1],
  MT: [5, 1, 2],
  WY: [6, 2, 1],
  UT: [6, 3, 2],
  AZ: [6, 5, 3],
  CO: [8, 3, 3, { align: 'right' }],
  NM: [9, 6, 2],
  ND: [7, 1, 1],
  SD: [7, 2, 1],
  NE: [8, 2, 3],
  KS: [11, 4, 2],
  OK: [11, 6, 5],
  TX: [10, 7, 7, { align: 'center' }],
  MN: [8, 0, 4],
  WI: [12, 0, 4],
  IA: [11, 2, 2],
  MO: [13, 3, 3],
  IL: [16, 1, 3],
  AR: [17, 7, 2],
  LA: [17, 9, 2],
  MS: [19, 9, 2],
  MI: [19, 0, 4, { short: 'top', align: 'right' }],
  IN: [19, 4, 3],
  KY: [19, 7, 3],
  TN: [21, 9, 5],
  AL: [20, 11, 2],
  GA: [22, 11, 4],
  FL: [21, 15, 5, { align: 'right' }],
  OH: [22, 4, 4],
  WV: [26, 6, 1],
  PA: [26, 3, 6],
  MD: [27, 6, 4],
  DE: [31, 6, 1],
  VA: [26, 8, 6],
  NC: [26, 10, 7],
  SC: [26, 12, 3],
  NY: [26, 0, 9, { short: 'top', align: 'right' }],
  NJ: [32, 3, 2],
  CT: [34, 5, 3],
  RI: [37, 5, 1],
  MA: [35, 2, 3],
  VT: [35, 0, 1],
  NH: [36, 0, 1],
  ME: [37, 0, 1],
}

// state: district numbers in fill order (row by row), when centroids read badly.
const ORDER = {}

const projection = geoAlbersUsa().scale(1300).translate([487.5, 305])

function rowSizes(n, width, short) {
  const rows = Math.ceil(n / width)
  const sizes = Array(rows).fill(width)
  const rest = n - width * (rows - 1)
  sizes[short === 'top' ? 0 : rows - 1] = rest
  return sizes
}

function placeState(state, centroids) {
  const [x0, y0, width, opts = {}] = LAYOUT[state]
  const n = APPORTIONMENT[state]
  const numbers = ORDER[state] ?? [...centroids.keys()].sort((a, b) => centroids.get(a)[1] - centroids.get(b)[1])
  const sizes = rowSizes(n, width, opts.short)
  const cells = []
  let k = 0
  sizes.forEach((size, row) => {
    let rowNumbers = numbers.slice(k, k + size)
    k += size
    if (!ORDER[state]) rowNumbers = rowNumbers.sort((a, b) => centroids.get(a)[0] - centroids.get(b)[0])
    const pad = size === width ? 0 : opts.align === 'right' ? width - size : opts.align === 'center' ? Math.floor((width - size) / 2) : 0
    rowNumbers.forEach((d, col) => cells.push({ id: districtId(state, d), state, x: x0 + pad + col, y: y0 + row }))
  })
  return cells
}

export function connected(cells) {
  const key = (c) => `${c.x},${c.y}`
  const all = new Set(cells.map(key))
  const seen = new Set([key(cells[0])])
  const queue = [cells[0]]
  while (queue.length) {
    const { x, y } = queue.pop()
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

function preview(tiles, width, height) {
  const s = 24
  const hue = (state) => (Object.keys(LAYOUT).indexOf(state) * 47) % 360
  const rects = tiles
    .map((t) => {
      const label = t.id.split('-')[1]
      return `<rect x="${t.x * s}" y="${t.y * s}" width="${s - 1}" height="${s - 1}" fill="hsl(${hue(t.state)} 45% 75%)"/>` +
        `<text x="${t.x * s + s / 2}" y="${t.y * s + 11}" font-size="7" text-anchor="middle">${t.state}</text>` +
        `<text x="${t.x * s + s / 2}" y="${t.y * s + 19}" font-size="7" text-anchor="middle">${label}</text>`
    })
    .join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width * s}" height="${height * s}" font-family="sans-serif">` +
    `<rect width="100%" height="100%" fill="white"/>${rects}</svg>`
}

async function main() {
  const { features, missing } = await loadAll({ fallback: true })
  const centroids = {}
  for (const f of features) {
    const p = projection(geoCentroid(f))
    if (!p) throw new Error(`${f.id}: centroid outside the projection`)
    ;(centroids[f.properties.state] ??= new Map()).set(f.properties.district, p)
  }

  const tiles = Object.keys(APPORTIONMENT).flatMap((s) => {
    if (!LAYOUT[s]) throw new Error(`no layout for ${s}`)
    return placeState(s, centroids[s])
  })

  const problems = []
  const taken = new Map()
  for (const t of tiles) {
    const k = `${t.x},${t.y}`
    if (taken.has(k)) problems.push(`${t.id} overlaps ${taken.get(k)} at ${k}`)
    taken.set(k, t.id)
  }
  for (const s of Object.keys(APPORTIONMENT)) {
    if (!connected(tiles.filter((t) => t.state === s))) problems.push(`${s} is not 4-connected`)
  }
  if (tiles.length !== 435) problems.push(`${tiles.length} tiles, expected 435`)

  const width = Math.max(...tiles.map((t) => t.x)) + 1
  const height = Math.max(...tiles.map((t) => t.y)) + 1
  const i = process.argv.indexOf('--preview')
  if (i > 0) writeFileSync(process.argv[i + 1], preview(tiles, width, height))
  if (problems.length) {
    console.error(problems.join('\n'))
    process.exit(1)
  }

  tiles.sort((a, b) => a.id.localeCompare(b.id))
  const out = {
    license: 'MIT',
    note: 'Torehancast House tile cartogram: one cell per district, x right and y down. Generated by web/scripts/build-tiles.mjs.',
    provisional: missing,
    width,
    height,
    tiles,
  }
  // One tile per line keeps diffs of hand-tuning readable.
  const rows = tiles.map((t) => '    ' + JSON.stringify(t)).join(',\n')
  const json = JSON.stringify({ ...out, tiles: [] }, null, 2).replace('"tiles": []', `"tiles": [\n${rows}\n  ]`)
  writeFileSync(resolve(WEB, 'src/data/houseTiles.json'), json + '\n')
  console.log(`houseTiles.json: ${tiles.length} tiles on ${width} x ${height}` +
    (missing.length ? `; ordered from CD119 shapes for ${missing.join(', ')} (rerun when their files land)` : ''))
}

await main()
