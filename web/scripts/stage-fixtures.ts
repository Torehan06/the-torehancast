/**
 * Staging only (PLAN.md F6): copies a fixture set into dist/data/replay/ so a
 * Firebase preview channel can render the page with no data bucket. Production
 * builds never run this: their data comes from the GCS bucket (VITE_DATA_BASE),
 * and no data file belongs in the Hosting build.
 *
 *   npm run build:staging            # fixtures/demo
 *   FIXTURE=cases/waiting npm run build:staging
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'

const web = resolve(import.meta.dirname, '..')
const source = join(web, 'fixtures', process.env.FIXTURE ?? 'demo')
const target = join(web, 'dist', 'data', 'replay')

if (!existsSync(join(web, 'dist', 'index.html'))) throw new Error('run the build first: dist/index.html is missing')
if (!existsSync(join(source, 'summary.json'))) throw new Error(`no summary.json in ${source}`)

rmSync(join(web, 'dist', 'data'), { recursive: true, force: true })
mkdirSync(target, { recursive: true })
cpSync(source, target, { recursive: true, filter: (src) => !src.endsWith('.md') })
console.log(`staged ${readdirSync(target).length} entries from ${source} into dist/data/replay/`)
