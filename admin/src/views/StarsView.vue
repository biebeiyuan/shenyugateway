<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCheckbox,
  NFormItem,
  NInput,
  NInputNumber,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { fetchConfig, saveConfig, type GatewayConfig } from '@/api/config'
import {
  connectStars,
  createStar,
  fetchStarGraph,
  markConstantStar,
  reviewStars,
  searchStars,
  sendStarFeedback,
  type StarCandidate,
  type StarGraphLink,
  type StarItem,
  type StarReviewItem,
} from '@/api/stars'

const message = useMessage()
const route = useRoute()
const router = useRouter()

const STAR_DEFAULTS: Partial<GatewayConfig> = {
  inject_star_prompt: true,
  enable_inline_star_capture: true,
  inject_stars: true,
  enable_gateway_tools: true,
  enable_star_embeddings: false,
  star_inject_limit: 3,
  star_review_new_limit: 5,
  star_review_candidates_per_star: 3,
  star_review_total_candidate_limit: 15,
  star_candidate_limit: 500,
  star_shadow_candidate_limit: 20,
  star_weight_content: 0.3,
  star_weight_keyword: 0.2,
  star_weight_harmony: 0.35,
  star_weight_chord: 0.18,
  star_weight_actr: 0.08,
  star_constant_bonus: 0.08,
  star_novelty_bonus: 0.04,
  star_ignored_penalty: 0.18,
}

type WorkMode = 'score' | 'settings' | 'write'

const config = ref<Partial<GatewayConfig>>({ ...STAR_DEFAULTS })
const savingConfig = ref(false)
const mode = ref<WorkMode>('score')

const graphStars = ref<StarItem[]>([])
const graphLinks = ref<StarGraphLink[]>([])
const mapLoading = ref(false)
const mapError = ref('')
const graphLimit = ref(320)
const graphSessionTag = ref('')
const selectedMapStarId = ref('')

const reviewItems = ref<StarReviewItem[]>([])
const reviewSessionTag = ref('')
const reviewing = ref(false)
const feedbackingKey = ref('')
const feedbackMarks = ref<Record<string, string>>({})
const expandedSeeds = ref<string[]>([])
const missedStarId = ref<Record<string, string>>({})
const connectName = ref('')
const connectNote = ref('')

const searchQuery = ref('')
const searchResults = ref<StarCandidate[]>([])
const searching = ref(false)

const createContent = ref('')
const createChord = ref('')
const createSessionTag = ref('')
const createConstant = ref(false)
const creating = ref(false)

const canvasRef = ref<HTMLCanvasElement | null>(null)
let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let starGroup: THREE.Group | null = null
let lineGroup: THREE.Group | null = null
let ambientPoints: THREE.Points | null = null
let frameId = 0
let glowTexture: THREE.CanvasTexture | null = null
let starGeometry: THREE.SphereGeometry | null = null

const raycaster = new THREE.Raycaster()
const pointer = new THREE.Vector2()
const starObjects = new Map<
  string,
  {
    mesh: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>
    glow: THREE.Sprite
    baseScale: number
    star: StarItem
  }
>()
const linkObjects: Array<{
  line: THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>
  source: string
  target: string
}> = []

const starCount = computed(() => graphStars.value.length)
const linkCount = computed(() => graphLinks.value.length)
const unscoredCount = computed(() =>
  reviewItems.value.reduce((total, item) => total + item.candidates.filter((candidate) => !feedbackFor(item.star, candidate)).length, 0),
)
const selectedMapStar = computed(() => graphStars.value.find((item) => item.id === selectedMapStarId.value) || null)
const isMapRoute = computed(() => route.path === '/stars/map')
const connectedMapStars = computed(() => {
  const selected = selectedMapStarId.value
  if (!selected) return []
  const ids = new Set<string>()
  for (const link of graphLinks.value) {
    if (link.source === selected) ids.add(link.target)
    if (link.target === selected) ids.add(link.source)
  }
  return graphStars.value.filter((star) => ids.has(star.id))
})

onMounted(async () => {
  await Promise.all([loadConfig(), loadGraph()])
  if (isMapRoute.value) {
    await nextTick()
    initStarfield()
  }
})

onBeforeUnmount(() => {
  teardownStarfield()
})

watch(isMapRoute, async (enabled) => {
  if (!enabled) {
    teardownStarfield()
    return
  }
  await nextTick()
  initStarfield()
  resizeStarfield()
  rebuildStarfield()
})

async function loadConfig() {
  try {
    const data = await fetchConfig()
    config.value = { ...STAR_DEFAULTS, ...data }
  } catch {
    message.error('读取 Star 设置失败')
  }
}

async function saveSettings() {
  savingConfig.value = true
  try {
    const result = await saveConfig({
      inject_star_prompt: config.value.inject_star_prompt,
      enable_inline_star_capture: config.value.enable_inline_star_capture,
      inject_stars: config.value.inject_stars,
      enable_gateway_tools: config.value.enable_gateway_tools,
      enable_star_embeddings: config.value.enable_star_embeddings,
      star_inject_limit: config.value.star_inject_limit,
      star_review_new_limit: config.value.star_review_new_limit,
      star_review_candidates_per_star: config.value.star_review_candidates_per_star,
      star_review_total_candidate_limit: config.value.star_review_total_candidate_limit,
      star_candidate_limit: config.value.star_candidate_limit,
      star_shadow_candidate_limit: config.value.star_shadow_candidate_limit,
      star_weight_content: config.value.star_weight_content,
      star_weight_keyword: config.value.star_weight_keyword,
      star_weight_harmony: config.value.star_weight_harmony,
      star_weight_chord: config.value.star_weight_chord,
      star_weight_actr: config.value.star_weight_actr,
      star_constant_bonus: config.value.star_constant_bonus,
      star_novelty_bonus: config.value.star_novelty_bonus,
      star_ignored_penalty: config.value.star_ignored_penalty,
    })
    config.value = { ...config.value, ...result.config }
    message.success('Star 设置已保存')
  } catch {
    message.error('保存 Star 设置失败')
  } finally {
    savingConfig.value = false
  }
}

function setStarQuietTools() {
  config.value.inject_star_prompt = false
  config.value.enable_inline_star_capture = false
  config.value.inject_stars = false
  config.value.enable_gateway_tools = true
  message.info('已切到静音星星模式，保存后生效')
}

function resetStarDefaults() {
  config.value = { ...config.value, ...STAR_DEFAULTS }
  message.info('已恢复 Star 默认值，保存后生效')
}

async function loadGraph() {
  mapLoading.value = true
  mapError.value = ''
  try {
    const result = await fetchStarGraph({
      status: 'active',
      limit: Number(graphLimit.value || 320),
      session_tag: graphSessionTag.value.trim() || undefined,
    })
    graphStars.value = result.stars || []
    graphLinks.value = result.links || []
    if (selectedMapStarId.value && !graphStars.value.some((item) => item.id === selectedMapStarId.value)) {
      selectedMapStarId.value = ''
    }
    if (!selectedMapStarId.value && graphStars.value.length) {
      selectedMapStarId.value = graphStars.value[0].id
    }
    rebuildStarfield()
  } catch {
    graphStars.value = []
    graphLinks.value = []
    mapError.value = '星图暂时没有连上网关'
    rebuildStarfield()
  } finally {
    mapLoading.value = false
  }
}

async function runReview() {
  reviewing.value = true
  try {
    const result = await reviewStars({
      limit_new: config.value.star_review_new_limit || 5,
      candidates_per_star: config.value.star_review_candidates_per_star || 3,
      total_candidate_limit: config.value.star_review_total_candidate_limit || 15,
      session_tag: reviewSessionTag.value.trim() || undefined,
    })
    reviewItems.value = result.items || []
    feedbackMarks.value = {}
    missedStarId.value = {}
    expandedSeeds.value = reviewItems.value[0]?.star?.id ? [reviewItems.value[0].star.id] : []
    message.success(`拿到 ${reviewItems.value.length} 颗新星`)
    await loadGraph()
  } catch {
    message.error('Review 失败')
  } finally {
    reviewing.value = false
  }
}

async function addStar() {
  const content = createContent.value.trim()
  if (!content) return
  creating.value = true
  try {
    const result = await createStar({
      content,
      chord: createChord.value.trim(),
      session_tag: createSessionTag.value.trim() || undefined,
      status: 'active',
      is_constant: createConstant.value,
      metadata: { surface: 'admin:stars' },
    })
    createContent.value = ''
    createChord.value = ''
    createConstant.value = false
    if (result.star_id) selectedMapStarId.value = result.star_id
    message.success('星星已写入')
    await loadGraph()
  } catch {
    message.error('写入星星失败')
  } finally {
    creating.value = false
  }
}

async function runSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const result = await searchStars({
      q,
      session_tag: graphSessionTag.value.trim() || undefined,
      limit: 8,
      log_run: true,
    })
    searchResults.value = result.items || []
  } catch {
    message.error('搜索星星失败')
  } finally {
    searching.value = false
  }
}

async function feedbackCandidate(seed: StarItem, candidate: StarCandidate, feedback: 'positive' | 'negative' | 'skipped') {
  const key = candidateKey(seed, candidate)
  feedbackingKey.value = `${key}:${feedback}`
  try {
    await sendStarFeedback({
      feedback,
      run_id: candidate.run_id,
      candidate_id: candidate.candidate_id,
      candidate_star_id: candidate.id,
      scored_by: '圆圆',
      metadata: { surface: 'admin:stars' },
    })
    feedbackMarks.value = { ...feedbackMarks.value, [key]: feedback }
    message.success(feedbackLabel(feedback))
  } catch {
    message.error('反馈失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function feedbackMissed(seed: StarItem, runId?: string | null) {
  const expected = (missedStarId.value[seed.id] || '').trim()
  if (!expected) return
  const key = `${seed.id}:missed`
  feedbackingKey.value = key
  try {
    await sendStarFeedback({
      feedback: 'missed',
      run_id: runId,
      expected_star_id: expected,
      scored_by: '圆圆',
      note: `Review ${seed.id} 时漏反`,
      metadata: { surface: 'admin:stars' },
    })
    missedStarId.value[seed.id] = ''
    message.success('已记下漏反')
  } catch {
    message.error('记录漏反失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function connectCandidate(seed: StarItem, candidate: StarCandidate) {
  const key = candidateKey(seed, candidate)
  feedbackingKey.value = `${key}:connected`
  try {
    await connectStars({
      star_ids: [seed.id, candidate.id],
      name: connectName.value.trim(),
      relation_type: 'constellation',
      scored_by: '圆圆',
      note: connectNote.value.trim(),
    })
    await sendStarFeedback({
      feedback: 'connected',
      run_id: candidate.run_id,
      candidate_id: candidate.candidate_id,
      candidate_star_id: candidate.id,
      scored_by: '圆圆',
      note: connectNote.value.trim(),
      metadata: { surface: 'admin:stars' },
    })
    feedbackMarks.value = { ...feedbackMarks.value, [key]: 'connected' }
    selectedMapStarId.value = seed.id
    message.success('星座连上了')
    await loadGraph()
  } catch {
    message.error('连线失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function toggleConstant(star: StarItem) {
  try {
    await markConstantStar(star.id, !star.is_constant)
    star.is_constant = !star.is_constant
    message.success(star.is_constant ? '已设为恒星' : '已取消恒星')
    rebuildStarfield()
  } catch {
    message.error('更新恒星失败')
  }
}

function candidateKey(seed: StarItem, candidate: StarCandidate): string {
  return candidate.candidate_id || `${seed.id}:${candidate.id}`
}

function feedbackFor(seed: StarItem, candidate: StarCandidate): string {
  return feedbackMarks.value[candidateKey(seed, candidate)] || ''
}

function toggleSeed(seedId: string) {
  if (expandedSeeds.value.includes(seedId)) {
    expandedSeeds.value = expandedSeeds.value.filter((item) => item !== seedId)
    return
  }
  expandedSeeds.value = [...expandedSeeds.value, seedId]
  selectedMapStarId.value = seedId
  updateHighlights()
}

function seedProgress(item: StarReviewItem): { done: number; total: number } {
  const total = item.candidates.length
  const done = item.candidates.filter((candidate) => feedbackFor(item.star, candidate)).length
  return { done, total }
}

function feedbackLabel(value: string): string {
  if (value === 'positive') return '这颗会更亮'
  if (value === 'negative') return '已记为不该反'
  if (value === 'skipped') return '先轻轻放过'
  if (value === 'connected') return '已连成星座'
  return '已记录'
}

function scoreParts(candidate: StarCandidate): string {
  const scores = candidate.scores || {}
  const labels: Array<[string, string]> = [
    ['content_score', '内容'],
    ['harmony_score', '和声'],
    ['chord_score', '和弦'],
    ['keyword_score', '词'],
    ['actr_score', '亮度'],
  ]
  return labels
    .filter(([key]) => scores[key] !== undefined)
    .map(([key, label]) => `${label} ${scores[key]}`)
    .join(' · ')
}

function rootLabel(star: StarItem): string {
  return star.chord || star.chord_root || '无和弦'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function hash01(value: string, salt = ''): number {
  return (hashString(`${salt}:${value}`) % 100000) / 100000
}

function normalizeRoot(root?: string | null): string {
  const value = (root || '').trim().toUpperCase()
  const flatMap: Record<string, string> = {
    DB: 'C#',
    EB: 'D#',
    GB: 'F#',
    AB: 'G#',
    BB: 'A#',
  }
  return flatMap[value] || value
}

function positionForStar(star: StarItem, index: number, total: number): THREE.Vector3 {
  const fifths = ['C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'G#', 'D#', 'A#', 'F']
  const root = normalizeRoot(star.chord_root || star.chord.match(/[A-G](?:#|b)?/i)?.[0])
  const rootIndex = Math.max(0, fifths.indexOf(root))
  const rootSlot = rootIndex >= 0 ? rootIndex : index % 12
  const identity = `${star.id}:${star.content}:${star.chord}`
  const angle = (rootSlot / 12) * Math.PI * 2 + (hash01(identity, 'angle') - 0.5) * 0.42
  const activation = Math.log1p(Number(star.activation_count || 0))
  const radius = 12 + hash01(identity, 'radius') * 24 + activation * 1.6 + Math.sqrt(Math.max(total, 1)) * 0.25
  const y = (hash01(identity, 'height') - 0.5) * 28 + (star.is_constant ? 3 : 0)
  const drift = (hash01(identity, 'drift') - 0.5) * 9
  return new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius + drift)
}

function brightnessForStar(star: StarItem): number {
  const activation = Math.log1p(Number(star.activation_count || 0))
  let recency = 0
  if (star.last_activated_at) {
    const ageDays = Math.max((Date.now() - Date.parse(star.last_activated_at)) / 86400000, 0)
    recency = Math.max(0, 0.26 - ageDays * 0.018)
  }
  return Math.min(1, 0.38 + activation * 0.14 + recency + (star.is_constant ? 0.22 : 0))
}

function colorForStar(star: StarItem): THREE.Color {
  const root = normalizeRoot(star.chord_root || star.chord.match(/[A-G](?:#|b)?/i)?.[0])
  const palette: Record<string, string> = {
    C: '#ffd7a8',
    G: '#b8e6c8',
    D: '#a9d8ff',
    A: '#f8b9c8',
    E: '#ffe38c',
    B: '#b8c7ff',
    'F#': '#c4f0e8',
    'C#': '#e8c4ff',
    'G#': '#ffc6e7',
    'D#': '#bde2ff',
    'A#': '#f4d1a1',
    F: '#cfe7ad',
  }
  return new THREE.Color(palette[root] || '#f3d8c7')
}

function initStarfield() {
  const canvas = canvasRef.value
  if (!canvas || renderer) return
  const rect = canvas.parentElement?.getBoundingClientRect()
  const width = Math.max(320, rect?.width || 900)
  const height = Math.max(360, rect?.height || 560)
  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(54, width / height, 0.1, 1000)
  camera.position.set(0, 18, 76)
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setSize(width, height, false)
  controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.055
  controls.autoRotate = true
  controls.autoRotateSpeed = 0.18
  controls.minDistance = 20
  controls.maxDistance = 160
  starGroup = new THREE.Group()
  lineGroup = new THREE.Group()
  scene.add(lineGroup)
  scene.add(starGroup)
  ambientPoints = createAmbientStars()
  scene.add(ambientPoints)
  glowTexture = createGlowTexture()
  starGeometry = new THREE.SphereGeometry(1, 24, 16)
  canvas.addEventListener('pointerdown', onMapPointer)
  window.addEventListener('resize', resizeStarfield)
  animateStarfield()
  rebuildStarfield()
}

function teardownStarfield() {
  if (frameId) cancelAnimationFrame(frameId)
  frameId = 0
  canvasRef.value?.removeEventListener('pointerdown', onMapPointer)
  window.removeEventListener('resize', resizeStarfield)
  clearGroup(starGroup)
  clearGroup(lineGroup)
  ambientPoints?.geometry.dispose()
  const ambientMaterial = ambientPoints?.material
  if (Array.isArray(ambientMaterial)) ambientMaterial.forEach((item) => item.dispose())
  else ambientMaterial?.dispose()
  glowTexture?.dispose()
  starGeometry?.dispose()
  controls?.dispose()
  renderer?.dispose()
  renderer = null
  scene = null
  camera = null
  controls = null
  starGroup = null
  lineGroup = null
  ambientPoints = null
  starObjects.clear()
  linkObjects.length = 0
}

function createGlowTexture(): THREE.CanvasTexture {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx) {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
    gradient.addColorStop(0, 'rgba(255,255,255,0.95)')
    gradient.addColorStop(0.22, 'rgba(255,215,168,0.62)')
    gradient.addColorStop(0.48, 'rgba(150,206,255,0.22)')
    gradient.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, size, size)
  }
  return new THREE.CanvasTexture(canvas)
}

function createAmbientStars(): THREE.Points {
  const count = 900
  const positions = new Float32Array(count * 3)
  const colors = new Float32Array(count * 3)
  for (let i = 0; i < count; i += 1) {
    const seed = `ambient-${i}`
    const theta = hash01(seed, 'theta') * Math.PI * 2
    const phi = Math.acos(hash01(seed, 'phi') * 2 - 1)
    const radius = 90 + hash01(seed, 'radius') * 90
    positions[i * 3] = Math.sin(phi) * Math.cos(theta) * radius
    positions[i * 3 + 1] = Math.cos(phi) * radius
    positions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * radius
    const warmth = hash01(seed, 'warmth')
    colors[i * 3] = 0.62 + warmth * 0.28
    colors[i * 3 + 1] = 0.66 + (1 - warmth) * 0.22
    colors[i * 3 + 2] = 0.78 + hash01(seed, 'blue') * 0.2
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  const material = new THREE.PointsMaterial({
    size: 0.42,
    vertexColors: true,
    transparent: true,
    opacity: 0.62,
    depthWrite: false,
  })
  return new THREE.Points(geometry, material)
}

function rebuildStarfield() {
  if (!scene || !starGroup || !lineGroup || !starGeometry || !glowTexture) return
  clearGroup(starGroup, false)
  clearGroup(lineGroup)
  starObjects.clear()
  linkObjects.length = 0
  const positions = new Map<string, THREE.Vector3>()
  graphStars.value.forEach((star, index) => {
    const position = positionForStar(star, index, graphStars.value.length)
    positions.set(star.id, position)
    const brightness = brightnessForStar(star)
    const color = colorForStar(star)
    const baseScale = 0.62 + brightness * 1.15 + (star.is_constant ? 0.34 : 0)
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.78 + brightness * 0.22,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(starGeometry as THREE.SphereGeometry, material)
    mesh.position.copy(position)
    mesh.scale.setScalar(baseScale)
    mesh.userData.starId = star.id
    const glowMaterial = new THREE.SpriteMaterial({
      map: glowTexture as THREE.CanvasTexture,
      color,
      transparent: true,
      opacity: 0.3 + brightness * 0.58,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    const glow = new THREE.Sprite(glowMaterial)
    glow.position.copy(position)
    glow.scale.setScalar(baseScale * (5.4 + brightness * 2.4))
    glow.userData.starId = star.id
    starGroup?.add(glow)
    starGroup?.add(mesh)
    starObjects.set(star.id, { mesh, glow, baseScale, star })
  })

  for (const link of graphLinks.value) {
    const source = positions.get(link.source)
    const target = positions.get(link.target)
    if (!source || !target) continue
    const geometry = new THREE.BufferGeometry().setFromPoints([source, target])
    const material = new THREE.LineBasicMaterial({
      color: link.relation_type === 'constellation' ? '#f5c27d' : '#9ed8d0',
      transparent: true,
      opacity: 0.26,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    const line = new THREE.Line(geometry, material)
    line.userData = { source: link.source, target: link.target }
    lineGroup.add(line)
    linkObjects.push({ line, source: link.source, target: link.target })
  }
  updateHighlights()
}

function clearGroup(group: THREE.Group | null, disposeGeometry = true) {
  if (!group) return
  while (group.children.length) {
    const child = group.children.pop()
    if (!child) continue
    child.traverse((object) => {
      const mesh = object as THREE.Mesh
      if (disposeGeometry) mesh.geometry?.dispose?.()
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material?.dispose?.()
    })
  }
}

function animateStarfield() {
  frameId = requestAnimationFrame(animateStarfield)
  controls?.update()
  if (renderer && scene && camera) {
    renderer.render(scene, camera)
  }
}

function resizeStarfield() {
  const canvas = canvasRef.value
  if (!canvas || !renderer || !camera) return
  const rect = canvas.parentElement?.getBoundingClientRect()
  const width = Math.max(320, rect?.width || 900)
  const height = Math.max(360, rect?.height || 560)
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
}

function onMapPointer(event: PointerEvent) {
  const canvas = canvasRef.value
  if (!canvas || !camera) return
  const rect = canvas.getBoundingClientRect()
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(pointer, camera)
  const intersects = raycaster.intersectObjects(Array.from(starObjects.values()).map((item) => item.mesh), false)
  if (!intersects.length) return
  const starId = String(intersects[0].object.userData.starId || '')
  if (!starId) return
  selectedMapStarId.value = starId
  updateHighlights()
}

function updateHighlights() {
  const selected = selectedMapStarId.value
  const connectedIds = new Set<string>()
  if (selected) {
    for (const link of graphLinks.value) {
      if (link.source === selected) connectedIds.add(link.target)
      if (link.target === selected) connectedIds.add(link.source)
    }
  }
  for (const [id, object] of starObjects.entries()) {
    const selectedSelf = id === selected
    const linked = connectedIds.has(id)
    const focus = !selected || selectedSelf || linked
    const scale = object.baseScale * (selectedSelf ? 1.8 : linked ? 1.34 : 1)
    object.mesh.scale.setScalar(scale)
    object.glow.scale.setScalar(scale * (selectedSelf ? 8.5 : linked ? 7 : 5.8))
    object.mesh.material.opacity = focus ? 1 : 0.28
    const glowMaterial = object.glow.material as THREE.SpriteMaterial
    glowMaterial.opacity = selectedSelf ? 0.96 : linked ? 0.74 : focus ? 0.38 : 0.12
  }
  for (const link of linkObjects) {
    const touches = selected && (link.source === selected || link.target === selected)
    link.line.material.opacity = touches ? 0.86 : selected ? 0.09 : 0.24
    link.line.material.color.set(touches ? '#ffe6a9' : '#9ed8d0')
  }
}
</script>

<template>
  <div class="stars-page" :class="{ 'map-page': isMapRoute }">
    <section v-if="isMapRoute" class="sky-section">
      <div class="sky-shell">
        <canvas ref="canvasRef" class="star-canvas" />
        <div class="sky-vignette"></div>
        <div class="sky-head">
          <div>
            <div class="eyebrow">Star Memory</div>
            <h2>记忆星图</h2>
          </div>
          <div class="sky-nav">
            <div class="sky-stats">
              <span>{{ starCount }} stars</span>
              <span>{{ linkCount }} links</span>
              <span v-if="mapLoading">syncing</span>
            </div>
            <NButton size="small" ghost @click="router.push('/stars')">回到星星</NButton>
          </div>
        </div>
        <div class="sky-controls">
          <input v-model="graphSessionTag" class="ghost-input compact" placeholder="session">
          <input v-model="graphLimit" class="ghost-input tiny" type="number" min="20" max="1000">
          <NButton size="small" :loading="mapLoading" @click="loadGraph">刷新星图</NButton>
        </div>
        <div v-if="mapError" class="map-error">{{ mapError }}</div>
        <aside class="memory-lens" :class="{ empty: !selectedMapStar }">
          <template v-if="selectedMapStar">
            <div class="lens-top">
              <NTag size="small">{{ rootLabel(selectedMapStar) }}</NTag>
              <NTag v-if="selectedMapStar.is_constant" size="small" type="warning">恒星</NTag>
              <NTag size="small">亮 {{ selectedMapStar.activation_count || 0 }}</NTag>
            </div>
            <p>{{ selectedMapStar.content }}</p>
            <div class="lens-time">updated {{ formatTime(selectedMapStar.updated_at) }}</div>
            <div v-if="connectedMapStars.length" class="linked-strip">
              <button
                v-for="star in connectedMapStars"
                :key="star.id"
                type="button"
                @click="selectedMapStarId = star.id; updateHighlights()"
              >
                <span>{{ rootLabel(star) }}</span>
                {{ star.content.slice(0, 26) }}
              </button>
            </div>
            <div class="lens-actions">
              <NButton size="tiny" @click="toggleConstant(selectedMapStar)">{{ selectedMapStar.is_constant ? '取消恒星' : '设为恒星' }}</NButton>
            </div>
          </template>
          <template v-else>
            <span>还没有星星</span>
          </template>
        </aside>
      </div>
    </section>

    <section v-else class="workbench">
      <div class="stars-head">
        <div>
          <div class="page-eyebrow">Star Memory</div>
          <h2>星星</h2>
          <p>一次一小口，连线、漏反、该反不该反都从这里记。</p>
        </div>
        <div class="head-actions">
          <NButton size="small" @click="router.push('/stars/map')">记忆星图</NButton>
          <NButton size="small" type="primary" :loading="reviewing" @click="runReview">拿一小批</NButton>
        </div>
      </div>

      <div class="mode-rail">
        <button type="button" :class="{ active: mode === 'score' }" @click="mode = 'score'">
          评分
          <span v-if="unscoredCount">{{ unscoredCount }}</span>
        </button>
        <button type="button" :class="{ active: mode === 'settings' }" @click="mode = 'settings'">配置</button>
        <button type="button" :class="{ active: mode === 'write' }" @click="mode = 'write'">写星</button>
      </div>

      <div v-if="mode === 'score'" class="score-space">
        <div class="soft-toolbar">
          <input v-model="reviewSessionTag" class="soft-input" placeholder="session_tag">
          <input v-model="connectName" class="soft-input" placeholder="星座名">
          <input v-model="connectNote" class="soft-input wide" placeholder="连线备注">
          <NButton size="small" type="primary" :loading="reviewing" @click="runReview">拿一小批</NButton>
        </div>

        <div v-if="!reviewItems.length" class="empty-score">
          <span>没有待评分批次</span>
          <NButton size="small" :loading="reviewing" @click="runReview">开始 review</NButton>
        </div>

        <div v-for="item in reviewItems" :key="item.star.id" class="seed-tile" :class="{ open: expandedSeeds.includes(item.star.id), done: seedProgress(item).done === seedProgress(item).total && item.candidates.length }">
          <button class="seed-head" type="button" @click="toggleSeed(item.star.id)">
            <span class="seed-dot" :class="{ warm: seedProgress(item).done, done: seedProgress(item).done === seedProgress(item).total && item.candidates.length }"></span>
            <span class="seed-chord">{{ rootLabel(item.star) }}</span>
            <span class="seed-text">{{ item.star.content }}</span>
            <span class="seed-count">{{ seedProgress(item).done }}/{{ item.candidates.length }}</span>
          </button>

          <div v-if="expandedSeeds.includes(item.star.id)" class="seed-body">
            <div class="missed-line">
              <input v-model="missedStarId[item.star.id]" class="soft-input wide" placeholder="漏反的 star id">
              <NButton size="small" :loading="feedbackingKey === `${item.star.id}:missed`" @click="feedbackMissed(item.star, item.run_id)">记漏反</NButton>
            </div>

            <div v-if="!item.candidates.length" class="empty-candidates">没有候选</div>
            <div v-for="candidate in item.candidates" :key="candidate.id" class="candidate-line" :class="feedbackFor(item.star, candidate) || 'fresh'">
              <button class="candidate-main" type="button" @click="selectedMapStarId = candidate.id; updateHighlights()">
                <span class="candidate-status">{{ feedbackFor(item.star, candidate) ? feedbackLabel(feedbackFor(item.star, candidate)) : '未评分' }}</span>
                <span class="candidate-chord">{{ rootLabel(candidate) }}</span>
                <span class="candidate-text">{{ candidate.content }}</span>
                <span class="candidate-score">{{ candidate.score ?? 0 }}</span>
              </button>
              <div class="candidate-detail">
                <span>{{ scoreParts(candidate) || 'no scores' }}</span>
                <div class="score-actions">
                  <NButton size="tiny" type="primary" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:connected`" @click="connectCandidate(item.star, candidate)">连起来</NButton>
                  <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:positive`" @click="feedbackCandidate(item.star, candidate, 'positive')">该反</NButton>
                  <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:negative`" @click="feedbackCandidate(item.star, candidate, 'negative')">不该反</NButton>
                  <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:skipped`" @click="feedbackCandidate(item.star, candidate, 'skipped')">先放过</NButton>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="mode === 'settings'" class="settings-space">
        <div class="toggle-grid">
          <label><NSwitch v-model:value="config.inject_star_prompt" /> <span>Star 提示</span></label>
          <label><NSwitch v-model:value="config.enable_inline_star_capture" /> <span>自动捕获</span></label>
          <label><NSwitch v-model:value="config.inject_stars" /> <span>聊天注入</span></label>
          <label><NSwitch v-model:value="config.enable_gateway_tools" /> <span>网关工具</span></label>
          <label><NSwitch v-model:value="config.enable_star_embeddings" /> <span>embedding</span></label>
        </div>

        <div class="number-grid">
          <NFormItem label="日常注入">
            <NInputNumber v-model:value="config.star_inject_limit" :min="1" :max="5" />
          </NFormItem>
          <NFormItem label="Review 新星">
            <NInputNumber v-model:value="config.star_review_new_limit" :min="1" :max="10" />
          </NFormItem>
          <NFormItem label="每星候选">
            <NInputNumber v-model:value="config.star_review_candidates_per_star" :min="1" :max="5" />
          </NFormItem>
          <NFormItem label="总候选">
            <NInputNumber v-model:value="config.star_review_total_candidate_limit" :min="1" :max="30" />
          </NFormItem>
        </div>

        <details class="advanced-settings">
          <summary>权重</summary>
          <div class="weight-grid">
            <NFormItem label="内容"><NInputNumber v-model:value="config.star_weight_content" :min="0" :max="2" :step="0.01" /></NFormItem>
            <NFormItem label="关键词"><NInputNumber v-model:value="config.star_weight_keyword" :min="0" :max="2" :step="0.01" /></NFormItem>
            <NFormItem label="和声"><NInputNumber v-model:value="config.star_weight_harmony" :min="0" :max="2" :step="0.01" /></NFormItem>
            <NFormItem label="和弦"><NInputNumber v-model:value="config.star_weight_chord" :min="0" :max="2" :step="0.01" /></NFormItem>
            <NFormItem label="亮度"><NInputNumber v-model:value="config.star_weight_actr" :min="0" :max="2" :step="0.01" /></NFormItem>
            <NFormItem label="恒星"><NInputNumber v-model:value="config.star_constant_bonus" :min="0" :max="1" :step="0.01" /></NFormItem>
            <NFormItem label="新鲜"><NInputNumber v-model:value="config.star_novelty_bonus" :min="0" :max="1" :step="0.01" /></NFormItem>
            <NFormItem label="忽略"><NInputNumber v-model:value="config.star_ignored_penalty" :min="0" :max="1" :step="0.01" /></NFormItem>
            <NFormItem label="候选池"><NInputNumber v-model:value="config.star_candidate_limit" :min="50" :max="5000" /></NFormItem>
            <NFormItem label="shadow"><NInputNumber v-model:value="config.star_shadow_candidate_limit" :min="3" :max="100" /></NFormItem>
          </div>
        </details>

        <div class="setting-actions">
          <NButton type="primary" :loading="savingConfig" @click="saveSettings">保存</NButton>
          <NButton :disabled="savingConfig" @click="setStarQuietTools">静音但留工具</NButton>
          <NButton :disabled="savingConfig" @click="resetStarDefaults">默认</NButton>
        </div>
      </div>

      <div v-else class="write-space">
        <div class="write-grid">
          <input v-model="createChord" class="soft-input" placeholder="Am / Cmaj7">
          <input v-model="createSessionTag" class="soft-input" placeholder="session_tag">
          <label class="constant-check"><NCheckbox v-model:checked="createConstant" /> 恒星</label>
        </div>
        <NInput v-model:value="createContent" type="textarea" :autosize="{ minRows: 4, maxRows: 9 }" placeholder="写下这一颗星" />
        <div class="write-actions">
          <NButton type="primary" :loading="creating" :disabled="!createContent.trim()" @click="addStar">写入星图</NButton>
        </div>

        <div class="search-strip">
          <input v-model="searchQuery" class="soft-input wide" placeholder="搜一颗星">
          <NButton size="small" :loading="searching" @click="runSearch">搜索</NButton>
        </div>
        <div v-if="searchResults.length" class="search-results">
          <button v-for="star in searchResults" :key="star.id" type="button" @click="selectedMapStarId = star.id; updateHighlights()">
            <span>{{ rootLabel(star) }}</span>
            {{ star.content }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.stars-page {
  max-width: 1320px;
  margin: 0 auto;
}

.stars-page.map-page {
  max-width: min(1440px, calc(100vw - 24px));
}

.sky-section {
  min-height: calc(100vh - 92px);
}

.sky-shell {
  position: relative;
  min-height: calc(100vh - 92px);
  overflow: hidden;
  border: 1px solid rgba(244, 210, 186, 0.24);
  border-radius: 8px;
  background:
    radial-gradient(circle at 30% 24%, rgba(176, 218, 205, 0.16), transparent 26%),
    radial-gradient(circle at 72% 68%, rgba(246, 193, 126, 0.12), transparent 30%),
    linear-gradient(135deg, #101522 0%, #171426 42%, #231826 100%);
  box-shadow: 0 18px 70px rgba(38, 31, 48, 0.18);
}

.star-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: grab;
}

.star-canvas:active {
  cursor: grabbing;
}

.sky-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(180deg, rgba(255, 246, 238, 0.05), transparent 42%),
    radial-gradient(circle at center, transparent 54%, rgba(12, 13, 22, 0.58));
}

.sky-head,
.sky-controls,
.memory-lens {
  position: absolute;
  z-index: 2;
}

.sky-head {
  top: 22px;
  left: 24px;
  right: 24px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  pointer-events: none;
}

.sky-nav {
  display: grid;
  gap: 10px;
  justify-items: end;
  pointer-events: auto;
}

.eyebrow {
  color: #f3cba4;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.sky-head h2 {
  margin: 3px 0 0;
  color: #fff8ed;
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 42px;
  font-weight: 400;
  letter-spacing: 0;
}

.sky-stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.sky-stats span,
.lens-top :deep(.n-tag) {
  background: rgba(255, 250, 244, 0.12) !important;
  color: #ffe8c7 !important;
  border: 1px solid rgba(255, 232, 199, 0.18) !important;
}

.sky-stats span {
  padding: 5px 9px;
  border-radius: 999px;
  color: #f3d3bf;
  font-size: 11px;
  backdrop-filter: blur(12px);
}

.sky-controls {
  left: 24px;
  bottom: 22px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.ghost-input,
.soft-input {
  min-height: 34px;
  padding: 6px 10px;
  border-radius: 6px;
  outline: none;
  transition: border-color 0.16s, background 0.16s;
}

.ghost-input {
  border: 1px solid rgba(255, 232, 199, 0.28);
  background: rgba(255, 250, 244, 0.1);
  color: #fff8ed;
}

.ghost-input::placeholder {
  color: rgba(255, 232, 199, 0.55);
}

.ghost-input.compact {
  width: 132px;
}

.ghost-input.tiny {
  width: 76px;
}

.map-error {
  position: absolute;
  left: 24px;
  bottom: 70px;
  z-index: 2;
  color: #ffd4c7;
  font-size: 12px;
}

.memory-lens {
  right: 22px;
  bottom: 22px;
  width: min(380px, calc(100% - 44px));
  padding: 16px;
  border: 1px solid rgba(255, 232, 199, 0.2);
  border-radius: 8px;
  background: rgba(22, 19, 31, 0.68);
  color: #fff7ee;
  backdrop-filter: blur(18px);
}

.memory-lens.empty {
  color: rgba(255, 247, 238, 0.7);
}

.lens-top {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.memory-lens p {
  margin: 0;
  max-height: 132px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
}

.lens-time {
  margin-top: 8px;
  color: rgba(255, 232, 199, 0.62);
  font-size: 11px;
}

.linked-strip {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.linked-strip button {
  padding: 8px 10px;
  border: 1px solid rgba(255, 232, 199, 0.16);
  border-radius: 6px;
  background: rgba(255, 250, 244, 0.08);
  color: #fff7ee;
  text-align: left;
  cursor: pointer;
}

.linked-strip span {
  margin-right: 8px;
  color: #f1c37a;
  font-weight: 600;
}

.lens-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.workbench {
  max-width: 980px;
  margin: 0 auto;
  border: 1px solid #f2ddd8;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  padding: 16px;
}

.stars-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid #f0e0dc;
  border-radius: 8px;
  background:
    radial-gradient(circle at 12% 18%, rgba(255, 224, 174, 0.26), transparent 34%),
    linear-gradient(135deg, #fffdfb 0%, #f8eef2 58%, #eff7f2 100%);
}

.page-eyebrow {
  color: #a08090;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.stars-head h2 {
  margin: 2px 0 3px;
  color: #4a3535;
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 34px;
  font-weight: 500;
  letter-spacing: 0;
}

.stars-head p {
  margin: 0;
  color: #8b7b79;
  font-size: 13px;
}

.head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.mode-rail {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.mode-rail button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid #ead4cf;
  border-radius: 999px;
  background: #fff;
  color: #846d77;
  cursor: pointer;
}

.mode-rail button.active {
  background: #4f4052;
  color: #fff7ee;
  border-color: #4f4052;
}

.mode-rail span {
  min-width: 18px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #f1c37a;
  color: #4f4052;
  font-size: 11px;
}

.soft-toolbar,
.missed-line,
.search-strip,
.setting-actions,
.write-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.soft-input {
  min-width: 150px;
  border: 1px solid #ead4cf;
  background: #fff;
  color: #4a3535;
}

.soft-input.wide {
  flex: 1;
  min-width: 240px;
}

.seed-tile {
  margin-top: 10px;
  border: 1px solid #ead4cf;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.seed-tile.open {
  border-color: #d4a7a2;
  box-shadow: 0 10px 26px rgba(98, 70, 82, 0.08);
}

.seed-tile.done {
  border-color: #b8d6c0;
}

.seed-head {
  width: 100%;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 0;
  background: transparent;
  color: #4a3535;
  cursor: pointer;
  text-align: left;
}

.seed-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #d9c8c4;
  box-shadow: 0 0 0 rgba(217, 200, 196, 0);
}

.seed-dot.warm {
  background: #e5b275;
  box-shadow: 0 0 14px rgba(229, 178, 117, 0.55);
}

.seed-dot.done {
  background: #92ba9c;
  box-shadow: 0 0 16px rgba(146, 186, 156, 0.5);
}

.seed-chord,
.candidate-chord {
  color: #967180;
  font-weight: 700;
  white-space: nowrap;
}

.seed-text,
.candidate-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seed-count,
.candidate-score,
.candidate-status {
  color: #b8a8a3;
  font-size: 12px;
  white-space: nowrap;
}

.seed-body {
  padding: 0 12px 12px;
}

.candidate-line {
  margin-top: 8px;
  border: 1px solid #f0e0dc;
  border-radius: 7px;
  background: #fffdfc;
}

.candidate-line.positive,
.candidate-line.connected {
  border-color: #b8d6c0;
  background: #fbfffc;
}

.candidate-line.negative {
  border-color: #e3b1ad;
  background: #fffafa;
}

.candidate-line.skipped {
  opacity: 0.72;
}

.candidate-main {
  width: 100%;
  display: grid;
  grid-template-columns: 74px 70px minmax(0, 1fr) 54px;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border: 0;
  background: transparent;
  color: #4a3535;
  cursor: pointer;
  text-align: left;
}

.candidate-detail {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 0 10px 10px;
  color: #7a6a6a;
  font-size: 12px;
  flex-wrap: wrap;
}

.score-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.empty-score,
.empty-candidates {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 86px;
  color: #9b8a88;
  font-size: 13px;
}

.toggle-grid,
.number-grid,
.weight-grid,
.write-grid {
  display: grid;
  gap: 10px;
}

.toggle-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.toggle-grid label,
.constant-check {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid #ead4cf;
  border-radius: 7px;
  background: #fff;
  color: #6b555b;
}

.number-grid {
  margin-top: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.advanced-settings {
  margin-top: 12px;
  border: 1px solid #ead4cf;
  border-radius: 8px;
  background: #fffdfc;
}

.advanced-settings summary {
  padding: 11px 12px;
  cursor: pointer;
  color: #846d77;
}

.weight-grid {
  padding: 0 12px 12px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.setting-actions {
  margin-top: 12px;
}

.write-grid {
  grid-template-columns: 1fr 1fr auto;
  margin-bottom: 10px;
}

.write-actions {
  margin-top: 10px;
  justify-content: flex-end;
}

.search-strip {
  margin-top: 16px;
}

.search-results {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.search-results button {
  padding: 10px;
  border: 1px solid #ead4cf;
  border-radius: 7px;
  background: #fff;
  color: #4a3535;
  text-align: left;
  cursor: pointer;
}

.search-results span {
  margin-right: 8px;
  color: #967180;
  font-weight: 700;
}

@media (max-width: 980px) {
  .sky-shell {
    min-height: 640px;
  }

  .sky-head {
    flex-direction: column;
  }

  .sky-nav {
    justify-items: start;
  }

  .memory-lens {
    left: 16px;
    right: 16px;
    width: auto;
  }

  .sky-controls {
    left: 16px;
    right: 16px;
    bottom: 204px;
  }

  .toggle-grid,
  .number-grid,
  .weight-grid,
  .write-grid {
    grid-template-columns: 1fr;
  }

  .candidate-main,
  .seed-head {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .candidate-status,
  .candidate-score {
    display: none;
  }

  .soft-input,
  .soft-input.wide {
    width: 100%;
  }

  .stars-head {
    flex-direction: column;
  }

  .head-actions {
    justify-content: flex-start;
  }
}
</style>
