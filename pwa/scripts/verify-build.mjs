import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const dist = resolve('dist')
const manifestPath = resolve(dist, 'build-info.json')

let buildInfo
try {
  buildInfo = JSON.parse(readFileSync(manifestPath, 'utf8'))
} catch (error) {
  throw new Error(`PWA build did not emit build-info.json: ${error instanceof Error ? error.message : String(error)}`)
}

if (buildInfo?.schema !== 1 || typeof buildInfo.buildId !== 'string' || !buildInfo.buildId) {
  throw new Error('PWA build-info.json is missing a usable build identity')
}

const assets = resolve(dist, 'assets')
const runtimeBundles = readdirSync(assets).filter((name) => name.endsWith('.js'))
const embedded = runtimeBundles.some((name) => readFileSync(resolve(assets, name), 'utf8').includes(buildInfo.buildId))
if (!embedded) throw new Error('PWA runtime bundle does not embed the build identity')

console.log(`PWA build identity verified: ${buildInfo.buildId}`)
