<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const START_DATE = new Date('2026-03-07')
const daysTogether = computed(() => {
  const now = new Date()
  const diff = now.getTime() - START_DATE.getTime()
  return Math.floor(diff / (1000 * 60 * 60 * 24))
})

const modules = [
  { icon: '♡', title: '档案', desc: '我们说过的每一句话', path: '/archive', size: 'full' },
  { icon: '☾', title: '便签', desc: 'little things we keep', path: '/mem0', size: 'half' },
  { icon: '✦', title: '矛盾书', desc: '冻结的原文', path: '/conflict', size: 'half' },
  { icon: '○', title: '日志', desc: '调试', path: '/logs', size: 'half' },
  { icon: '☷', title: '线程', desc: '会话', path: '/sessions', size: 'half' },
  { icon: '❀', title: '日历', desc: '日记', path: '/calendar', size: 'third' },
  { icon: '☆', title: '海信', desc: '通道', path: '/hisense', size: 'third' },
  { icon: '⚙', title: '配置', desc: '参数', path: '/config', size: 'third' },
  { icon: '⚡', title: '工具报错', desc: '错误记录', path: '/tool-errors', size: 'third' },
]

function go(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="home-wrapper">
    <div class="hero">
      <div class="hero-mascots">
        <span class="mascot">🐙</span>
        <span class="mascot-heart">♡</span>
        <span class="mascot">🦦</span>
      </div>
      <div class="hero-days">
        <span class="days-number">{{ daysTogether }}</span>
        <span class="days-unit">days</span>
      </div>
      <p class="hero-since">since Mar 7, 2026</p>
    </div>

    <div class="bento">
      <button
        v-for="m in modules"
        :key="m.path"
        class="cell"
        :class="m.size"
        @click="go(m.path)"
      >
        <span class="cell-icon">{{ m.icon }}</span>
        <div class="cell-text">
          <span class="cell-title">{{ m.title }}</span>
          <span class="cell-desc">{{ m.desc }}</span>
        </div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.home-wrapper {
  max-width: 420px;
  margin: 0 auto;
  padding: 0 12px;
  min-height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
}

/* Hero */
.hero {
  text-align: center;
  padding: 28px 0 22px;
}

.hero-mascots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 10px;
}

.mascot {
  font-size: 28px;
  line-height: 1;
}

.mascot-heart {
  font-size: 14px;
  color: #c094a8;
  animation: heartbeat 2.5s ease-in-out infinite;
}

@keyframes heartbeat {
  0%, 100% { transform: scale(1); opacity: 0.7; }
  50% { transform: scale(1.2); opacity: 1; }
}

.hero-days {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
  margin-bottom: 4px;
}

.days-number {
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 52px;
  font-weight: 300;
  color: #8b7082;
  line-height: 1;
  letter-spacing: -1px;
}

.days-unit {
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 17px;
  font-weight: 400;
  color: #b8a8a3;
  letter-spacing: 2px;
}

.hero-since {
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 12px;
  color: #c4b0ab;
  letter-spacing: 1px;
}

/* Bento Grid */
.bento {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  flex: 1;
  align-content: start;
}

.cell {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px 14px 14px;
  border: 1px solid #f0e0dc;
  border-radius: 16px;
  cursor: pointer;
  transition: all 0.25s ease;
  text-align: left;
  background: #fff;
  position: relative;
}

.cell.full {
  grid-column: span 6;
  padding: 22px 20px 18px;
  background: linear-gradient(150deg, #faf0ee 0%, #f5edf3 50%, #fff 100%);
  min-height: 80px;
}

.cell.half {
  grid-column: span 3;
  min-height: 76px;
}

.cell.third {
  grid-column: span 2;
  min-height: 68px;
  padding: 14px 12px 12px;
}

.cell:hover {
  border-color: #c9a8b6;
  box-shadow: 0 4px 20px rgba(139, 112, 130, 0.1);
  transform: translateY(-1px);
}

.cell-icon {
  font-size: 16px;
  color: #a08090;
  margin-bottom: 8px;
  opacity: 0.75;
}

.cell.full .cell-icon {
  font-size: 18px;
}

.cell.third .cell-icon {
  font-size: 14px;
  margin-bottom: 6px;
}

.cell-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cell-title {
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 15px;
  font-weight: 600;
  color: #4a3535;
}

.cell.full .cell-title {
  font-size: 16px;
}

.cell.third .cell-title {
  font-size: 13px;
}

.cell:hover .cell-title {
  color: #8b7082;
}

.cell-desc {
  font-size: 11px;
  color: #c4b0ab;
  font-style: italic;
}

.cell.third .cell-desc {
  font-size: 10px;
}

@media (max-width: 400px) {
  .bento {
    grid-template-columns: repeat(4, 1fr);
  }
  .cell.full {
    grid-column: span 4;
  }
  .cell.half {
    grid-column: span 2;
  }
  .cell.third {
    grid-column: span 2;
  }
}
</style>
