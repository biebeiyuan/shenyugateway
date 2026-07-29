import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function fail(message) {
  throw new Error(message)
}

const deploymentUrl = process.env.PWA_DEPLOY_URL?.trim()
if (!deploymentUrl) fail('Set PWA_DEPLOY_URL to the production /chat/ URL before verifying deployment.')

const target = new URL(deploymentUrl)
if (!target.pathname.endsWith('/chat/')) {
  fail('PWA_DEPLOY_URL must point to the production /chat/ URL, including the trailing slash.')
}

let localBuild
try {
  localBuild = JSON.parse(readFileSync(resolve('dist/build-info.json'), 'utf8'))
} catch (error) {
  fail(`Read the local PWA build first: ${error instanceof Error ? error.message : String(error)}`)
}

if (localBuild?.schema !== 1 || typeof localBuild.revision !== 'string' || !localBuild.revision || localBuild.revision === 'unknown') {
  fail('Local build-info.json has no usable source revision.')
}

const headers = new Headers({ 'Cache-Control': 'no-cache' })
const token = process.env.GATEWAY_API_KEY?.trim()
if (token) headers.set('Authorization', `Bearer ${token}`)

const buildInfoUrl = new URL('build-info.json', target)
const response = await fetch(buildInfoUrl, { headers, cache: 'no-store' })
if (!response.ok) {
  const authHint = response.status === 401 && !token ? ' Set GATEWAY_API_KEY for this protected gateway.' : ''
  fail(`Production build-info request returned HTTP ${response.status}.${authHint}`)
}

const deployedBuild = await response.json()
if (deployedBuild?.schema !== 1 || typeof deployedBuild.revision !== 'string' || !deployedBuild.revision || deployedBuild.revision === 'unknown') {
  fail('Production build-info.json has an invalid format.')
}
if (deployedBuild.revision !== localBuild.revision) {
  fail(`PWA deployment mismatch: local ${localBuild.revision}, production ${deployedBuild.revision}.`)
}

console.log(`PWA deployment source verified: ${localBuild.revision} (local ${localBuild.buildId}, production ${deployedBuild.buildId})`)
