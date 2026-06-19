<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, useMessage } from 'naive-ui'
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  Group,
  Line,
  LineBasicMaterial,
  Material,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Raycaster,
  Scene,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { fetchStarGraph, markConstantStar, type StarGraphLink, type StarItem } from '@/api/stars'
import {
  constellationsFromGraph,
  formatTime,
  normalizeRoot,
  rootFromStar,
  rootLabel,
  sortLinks,
  sourceMeta,
} from './starUi'
import { playConstellationMelody } from './starMelody'

const props = withDefaults(defineProps<{ initialStarId?: string }>(), {
  initialStarId: '',
})

const message = useMessage()
const router = useRouter()

const graphStars = ref<StarItem[]>([])
const graphLinks = ref<StarGraphLink[]>([])
const mapLoading = ref(false)
const mapError = ref('')
const graphLimit = ref(320)
const graphSessionTag = ref('')
const selectedMapStarId = ref('')
const playingConstellation = ref(false)

const canvasRef = ref<HTMLCanvasElement | null>(null)
let renderer: WebGLRenderer | null = null
let scene: Scene | null = null
let camera: PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let starGroup: Group | null = null
let lineGroup: Group | null = null
let ambientPoints: Points | null = null
let frameId = 0
let glowTexture: CanvasTexture | null = null
let starGeometry: SphereGeometry | null = null

const raycaster = new Raycaster()
const pointer = new Vector2()
const starObjects = new Map<
  string,
  {
    mesh: Mesh<SphereGeometry, MeshBasicMaterial>
    glow: Sprite
    baseScale: number
    star: StarItem
  }
>()
const linkObjects: Array<{
  line: Line<BufferGeometry, LineBasicMaterial>
  source: string
  target: string
}> = []

const starCount = computed(() => graphStars.value.length)
const linkCount = computed(() => graphLinks.value.length)
const mapConstellations = computed(() => constellationsFromGraph(graphStars.value, graphLinks.value))
const selectedMapStar = computed(() => graphStars.value.find((item) => item.id === selectedMapStarId.value) || null)
const connectedMapStarRows = computed(() => {
  const selected = selectedMapStarId.value
  if (!selected) return []
  const rows: Array<{ star: StarItem; link: StarGraphLink; order: number }> = []
  const starById = new Map(graphStars.value.map((star) => [star.id, star]))
  for (const link of sortLinks(graphLinks.value)) {
    const otherId = link.source === selected ? link.target : link.target === selected ? link.source : ''
    const star = otherId ? starById.get(otherId) : null
    if (star) {
      rows.push({
        star,
        link,
        order: typeof link.position === 'number' ? link.position + 1 : rows.length + 1,
      })
    }
  }
  return rows
})

onMounted(async () => {
  await loadGraph()
  await nextTick()
  initStarfield()
})

onBeforeUnmount(() => {
  teardownStarfield()
})

watch(
  () => props.initialStarId,
  (starId) => {
    if (starId && graphStars.value.some((item) => item.id === starId)) {
      selectMapStar(starId)
    }
  },
)

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
    if (props.initialStarId && graphStars.value.some((item) => item.id === props.initialStarId)) {
      selectedMapStarId.value = props.initialStarId
    } else if (selectedMapStarId.value && !graphStars.value.some((item) => item.id === selectedMapStarId.value)) {
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

function jumpToNextConstellation() {
  if (!mapConstellations.value.length) return
  const currentIndex = mapConstellations.value.findIndex((item) => item.starIds.includes(selectedMapStarId.value))
  const next = mapConstellations.value[(currentIndex + 1 + mapConstellations.value.length) % mapConstellations.value.length]
  if (next?.starIds[0]) selectMapStar(next.starIds[0])
}

function closeMapLens() {
  selectedMapStarId.value = ''
  updateHighlights()
}

function selectMapStar(starId: string) {
  selectedMapStarId.value = starId
  updateHighlights()
}

function selectedConstellation() {
  const selected = selectedMapStarId.value
  return mapConstellations.value.find((item) => item.starIds.includes(selected)) || null
}

async function playSelectedConstellation() {
  const constellation = selectedConstellation() || mapConstellations.value[0]
  if (!constellation || constellation.stars.length < 2 || playingConstellation.value) return
  playingConstellation.value = true
  try {
    await playConstellationMelody(constellation.stars)
  } catch {
    message.error('旋律播放失败')
  } finally {
    playingConstellation.value = false
  }
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

function positionForStar(star: StarItem, index: number, total: number): Vector3 {
  const fifths = ['C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'G#', 'D#', 'A#', 'F']
  const root = normalizeRoot(rootFromStar(star))
  const rootIndex = Math.max(0, fifths.indexOf(root))
  const rootSlot = rootIndex >= 0 ? rootIndex : index % 12
  const identity = `${star.id}:${star.content}:${star.chord}`
  const angle = (rootSlot / 12) * Math.PI * 2 + (hash01(identity, 'angle') - 0.5) * 0.42
  const activation = Math.log1p(Number(star.activation_count || 0))
  const radius = 12 + hash01(identity, 'radius') * 24 + activation * 1.6 + Math.sqrt(Math.max(total, 1)) * 0.25
  const y = (hash01(identity, 'height') - 0.5) * 28 + (star.is_constant ? 3 : 0)
  const drift = (hash01(identity, 'drift') - 0.5) * 9
  return new Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius + drift)
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

function colorForStar(star: StarItem): Color {
  const root = normalizeRoot(rootFromStar(star))
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
  return new Color(palette[root] || '#f3d8c7')
}

function initStarfield() {
  const canvas = canvasRef.value
  if (!canvas || renderer) return
  const rect = canvas.parentElement?.getBoundingClientRect()
  const width = Math.max(320, rect?.width || 900)
  const height = Math.max(360, rect?.height || 560)
  scene = new Scene()
  camera = new PerspectiveCamera(54, width / height, 0.1, 1000)
  camera.position.set(0, 18, 76)
  renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setSize(width, height, false)
  controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.055
  controls.autoRotate = true
  controls.autoRotateSpeed = 0.18
  controls.minDistance = 20
  controls.maxDistance = 160
  starGroup = new Group()
  lineGroup = new Group()
  scene.add(lineGroup)
  scene.add(starGroup)
  ambientPoints = createAmbientStars()
  scene.add(ambientPoints)
  glowTexture = createGlowTexture()
  starGeometry = new SphereGeometry(1, 24, 16)
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

function createGlowTexture(): CanvasTexture {
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
  return new CanvasTexture(canvas)
}

function createAmbientStars(): Points {
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
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(positions, 3))
  geometry.setAttribute('color', new BufferAttribute(colors, 3))
  const material = new PointsMaterial({
    size: 0.42,
    vertexColors: true,
    transparent: true,
    opacity: 0.62,
    depthWrite: false,
  })
  return new Points(geometry, material)
}

function rebuildStarfield() {
  if (!scene || !starGroup || !lineGroup || !starGeometry || !glowTexture) return
  clearGroup(starGroup, false)
  clearGroup(lineGroup)
  starObjects.clear()
  linkObjects.length = 0
  const positions = new Map<string, Vector3>()
  graphStars.value.forEach((star, index) => {
    const position = positionForStar(star, index, graphStars.value.length)
    positions.set(star.id, position)
    const brightness = brightnessForStar(star)
    const color = colorForStar(star)
    const baseScale = 0.62 + brightness * 1.15 + (star.is_constant ? 0.34 : 0)
    const material = new MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.78 + brightness * 0.22,
      depthWrite: false,
    })
    const mesh = new Mesh(starGeometry as SphereGeometry, material)
    mesh.position.copy(position)
    mesh.scale.setScalar(baseScale)
    mesh.userData.starId = star.id
    const glowMaterial = new SpriteMaterial({
      map: glowTexture as CanvasTexture,
      color,
      transparent: true,
      opacity: 0.3 + brightness * 0.58,
      blending: AdditiveBlending,
      depthWrite: false,
    })
    const glow = new Sprite(glowMaterial)
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
    const geometry = new BufferGeometry().setFromPoints([source, target])
    const material = new LineBasicMaterial({
      color: link.relation_type === 'constellation' ? '#f5c27d' : '#9ed8d0',
      transparent: true,
      opacity: 0.26,
      blending: AdditiveBlending,
      depthWrite: false,
    })
    const line = new Line(geometry, material)
    line.userData = { source: link.source, target: link.target }
    lineGroup.add(line)
    linkObjects.push({ line, source: link.source, target: link.target })
  }
  updateHighlights()
}

function clearGroup(group: Group | null, disposeGeometry = true) {
  if (!group) return
  while (group.children.length) {
    const child = group.children.pop()
    if (!child) continue
    child.traverse((object) => {
      const mesh = object as Mesh
      if (disposeGeometry) mesh.geometry?.dispose?.()
      const material = mesh.material as Material | Material[] | undefined
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
    const glowMaterial = object.glow.material as SpriteMaterial
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
  <section class="sky-section">
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
            <button type="button" :disabled="!mapConstellations.length" @click="jumpToNextConstellation">
              {{ mapConstellations.length }} 星座 / {{ linkCount }} 连接
            </button>
            <span v-if="mapLoading">syncing</span>
          </div>
          <NButton size="small" ghost @click="router.push('/stars')">回到星星</NButton>
        </div>
      </div>
      <div class="sky-controls">
        <label class="ghost-field">
          <span>session_tag</span>
          <input v-model="graphSessionTag" class="ghost-input compact" placeholder="留空=全部">
        </label>
        <label class="ghost-field">
          <span>加载上限</span>
          <input v-model="graphLimit" class="ghost-input tiny" type="number" min="20" max="1000">
        </label>
        <NButton size="small" :loading="mapLoading" @click="loadGraph">刷新星图</NButton>
      </div>
      <div v-if="mapError" class="map-error">{{ mapError }}</div>
      <aside class="memory-lens" :class="{ empty: !selectedMapStar }">
        <template v-if="selectedMapStar">
          <div class="lens-top">
            <div class="lens-tags">
              <NTag size="small">{{ rootLabel(selectedMapStar) }}</NTag>
              <NTag v-if="selectedMapStar.is_constant" size="small" type="warning">恒星</NTag>
              <NTag size="small">亮 {{ selectedMapStar.activation_count || 0 }}</NTag>
            </div>
            <button class="lens-close" type="button" aria-label="收起详情" @click="closeMapLens">×</button>
          </div>
          <p>{{ selectedMapStar.content }}</p>
          <div v-if="selectedMapStar.source_excerpt" class="source-box">
            <div class="source-meta">{{ sourceMeta(selectedMapStar) }}</div>
            <div class="source-text">{{ selectedMapStar.source_excerpt }}</div>
          </div>
          <div class="lens-time">updated {{ formatTime(selectedMapStar.updated_at) }}</div>
          <div v-if="connectedMapStarRows.length" class="linked-strip">
            <button
              v-for="row in connectedMapStarRows"
              :key="`${row.link.id || row.star.id}:${row.star.id}`"
              type="button"
              @click="selectMapStar(row.star.id)"
            >
              <span class="link-order">#{{ row.order }}</span>
              <span>{{ rootLabel(row.star) }}</span>
              {{ row.star.content.slice(0, 32) }}
            </button>
          </div>
          <div class="lens-actions">
            <NButton
              v-if="selectedConstellation()"
              size="tiny"
              :loading="playingConstellation"
              @click="playSelectedConstellation"
            >
              听旋律
            </NButton>
            <NButton size="tiny" @click="toggleConstant(selectedMapStar)">{{ selectedMapStar.is_constant ? '取消恒星' : '设为恒星' }}</NButton>
          </div>
        </template>
        <template v-else>
          <span>还没有星星</span>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
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
.sky-stats button,
.lens-top :deep(.n-tag) {
  background: rgba(255, 250, 244, 0.12) !important;
  color: #ffe8c7 !important;
  border: 1px solid rgba(255, 232, 199, 0.18) !important;
}

.sky-stats span,
.sky-stats button {
  padding: 5px 9px;
  border-radius: 999px;
  color: #f3d3bf;
  font-size: 11px;
  backdrop-filter: blur(12px);
}

.sky-stats button {
  cursor: pointer;
}

.sky-stats button:disabled {
  cursor: default;
  opacity: 0.62;
}

.sky-controls {
  left: 24px;
  bottom: 22px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.ghost-field {
  display: grid;
  gap: 4px;
  color: rgba(255, 232, 199, 0.68);
  font-size: 11px;
}

.ghost-input {
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid rgba(255, 232, 199, 0.28);
  border-radius: 6px;
  background: rgba(255, 250, 244, 0.1);
  color: #fff8ed;
  outline: none;
  transition: border-color 0.16s, background 0.16s;
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
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.lens-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.lens-close {
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  border: 1px solid rgba(255, 232, 199, 0.2);
  border-radius: 50%;
  background: rgba(255, 250, 244, 0.08);
  color: #ffe8c7;
  cursor: pointer;
  line-height: 1;
}

.memory-lens p {
  margin: 0;
  max-height: 132px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
}

.source-box {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid rgba(255, 232, 199, 0.18);
  border-radius: 7px;
  background: rgba(255, 250, 244, 0.08);
}

.source-meta {
  margin-bottom: 6px;
  color: #f2ceb8;
  font-size: 11px;
}

.source-text {
  max-height: 180px;
  overflow: auto;
  color: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 12px;
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

.linked-strip .link-order {
  display: inline-flex;
  min-width: 28px;
  color: #9ed8d0;
}

.lens-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
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
}
</style>
