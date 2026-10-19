/**
 * Validates a tree of published JSON against the strict contract in
 * src/data/contract.ts. The Python drift test (tests/web/) runs this on fresh
 * publisher output, so the publisher and the page can't silently drift apart.
 *
 *   npm run validate-json -- <dir> [--require-v1]
 *
 * --require-v1 also demands the M3 fields (`modeled`, per-candidate `votes`).
 * Exits 1 and lists every problem if anything doesn't match.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { basename, join, relative } from 'node:path'
import { validatePublicFile } from '../src/data/parse'

function* jsonFiles(dir: string): Generator<string> {
  for (const name of readdirSync(dir).sort()) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* jsonFiles(path)
    else if (name.endsWith('.json')) yield path
  }
}

const args = process.argv.slice(2)
const requireV1 = args.includes('--require-v1')
const dirs = args.filter((a) => !a.startsWith('--'))
if (dirs.length === 0) {
  console.error('usage: validate-json <dir>... [--require-v1]')
  process.exit(2)
}

let files = 0
const problems: string[] = []
for (const dir of dirs) {
  for (const path of jsonFiles(dir)) {
    files++
    let raw: unknown
    try {
      raw = JSON.parse(readFileSync(path, 'utf8'))
    } catch (e) {
      problems.push(`${relative(dir, path)}: invalid JSON (${(e as Error).message})`)
      continue
    }
    const rel = relative(dir, path)
    for (const p of validatePublicFile(basename(path), raw, requireV1)) problems.push(p.replace(basename(path), rel))
  }
}

if (files === 0) problems.push('no JSON files found')
for (const p of problems) console.error(p)
console.log(`${files} files checked, ${problems.length} problems`)
process.exit(problems.length ? 1 : 0)
