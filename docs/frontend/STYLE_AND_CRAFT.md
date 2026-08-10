# Admin 前端：风格与手感基线

这份文档是 admin 前端的"对照物"：新元素进来之前先对照它，做完改动拿它验收。
两半内容——**看得见的风格**（视觉规范）和**摸得着的手感**（工程规范），外加验收流程和前端地图。

风格血统声明：角色语义色与「昼夜同树、换色不换布局」的手法学自 kimi-manor
（CC BY-NC，署名已写在 `admin/src/theme/tokens.css` 文件头）；「新元素照此站边」
的规矩学自 kimi-room；手感工程规范摘编自 webview-native-feel-2（《把网页 App
磨出原生手感 2.0》）。学方法，不搬代码与素材。

## 一、视觉基线（昼场）

| 部位 | 值 | 说明 |
|---|---|---|
| 页面底 | `#fdf6f4` | 淡奶油平底，不铺渐变 |
| 纸/卡 | `#fff` | 纯白，发丝边 `#f0e0dc` |
| 芯片/大卡渐变起点 | `#faf0ee` | `--sy-rose-soft` |
| 主色（交互） | `#c094a8` | 软玫瑰粉，深档 `#a07888` / `#8b7082` |
| 墨 | `#4a3535` / `#5f4747` | 暖深棕，mute 用 `rgba(74,53,53,…)` |
| 字体 | Cormorant Garamond + Noto Serif SC | 数据用 JetBrains Mono |

**角色语义色（站边规矩）**：你 = 软玫瑰粉 `--sy-self`；沈予 = 深松绿 `--sy-resident`；
系统 = 墨/纸灰 `--sy-sys-*`。新元素只许归入已有角色，不许自带新色。

**金的边界**：`--sy-gilt`、`--sy-hair-gilt*`、软木板 `--sy-board*` 只许出现在
记忆网络视图（`views/MemoryGraphView.vue` 与 `views/memory-graph/`）内部，
全站其它地方不描金。夜场（近黑+金）是另一套皮肤，由 `data-theme='night'` 整体切换。

**花纹挂法（探索区的护栏）**：圆圆想要更丰富的花纹，但花纹必须遵守装饰层三不许——
不响应点击、不参与布局、少了它不缺信息。花纹做成独立组件（如 `SyGlyph`），
一次只装饰一个"房间"，preview 看过喜欢再推广；任何一处都能单独摘掉。

**待收敛的账目**（知道就好，改动时顺手靠拢，不专程返工）：

- 断点目前 720px（RecallBoard）与 640px（纸片组件）并存，目标统一 720px。
- 字号目前 9~52px 十余个散值，目标收成一档级数（11.5 / 12.5 / 14 / 17 / 22 / 52）。

## 二、手感家法（工程规范）

移动端浏览器有两个世界：**合成器的世界**（`transform`、`opacity`，GPU 贴放，
满帧）和**主线程的世界**（`height`、`margin`、`top` 等布局属性，每改一帧全列表
重排）。家法都是它的推论：

1. 动画位移一律 `transform`，显隐一律 `opacity`；布局属性只许一步到位，绝不过渡。
   要"布局变了还想滑过去"，用 FLIP（布局先跳终态，视觉用 transform 滑回）。
2. **动画的 fill 姿势会压住普通样式**（2026-08 想起板事故）：移动端要把一个
   组件"放平"时，`transform: none` 不够，必须连 `animation` 一起关。
3. `prefers-reduced-motion` 下动画全停，但信息一条不少。
4. 桌面浏览器永远复现不出真机的部分毛病（视口、键盘、滚动惯性）——
   桌面绿灯不作数，手机视口才是第一现场（见 `AGENTS.md` PWA 三规则与手机端条款）。
5. 盲改配额两针：两次没修中就停手上探针（量测/采样），不许第三针盲赌。

## 三、出生清单（新组件落地前自查）

**新页面**：手机视口（390px）先行设计，桌面是放大版不是反过来；数据读取走
`api/http.ts` 总闸；演示模式要有对应 fixture（见下）。

**新弹层/覆盖层**：开合动画只用 transform/opacity；Esc 与点遮罩都能关；
`prefers-reduced-motion` 下内容完整；移动端是全屏还是半屏要想清楚。

**新列表**：增删的移动画只动 transform/opacity，高度收拢用"替身淡出 +
真身立即抽流"，别过渡 height；手机视口下不许有横向溢出。

**新输入框**：回车提交、清除按钮、loading 态三件套；手机上弹键盘不顶飞布局
（随键盘移动的元素只许 translateY）。

## 四、验收流程（不许拿圆圆当探针）

改动交付之前，自己先在手机视口看过：

```bash
cd admin
npm run preview:lan          # 构建 + 起隔离预览，打印手机直连网址（演示数据）
node scripts/mobile-shots.mjs  # 390×844 触屏模拟走关键路径，截图到 admin/.shots/
```

- **演示数据模式**：任何地址加 `?demo=1`（或预览脚本打印的网址），读取请求由
  `src/demo/` 拦截返回编造样本；页头出现"演示数据"徽章。写操作假成功不落库。
  生产构建也带这段代码，但不开开关完全不生效。
- 手机"拒绝访问"打不开时：WSL mirrored 模式下 **Windows 防火墙拦局域网入站**，
  一次性放行该端口即可（命令见 `preview:lan` 启动时的打印）。
- 网址基本不变：端口固定 `18112`；前面的 IP 是路由器分给这台电脑的，家用一般
  长期不变。万一变了（如路由器重启后），以 `npm run preview:lan` 启动时打印的
  地址为准。
- 截图要人眼过一遍——"测过"和"看过"是两回事。
- 圆圆的手机直接打开 `preview:lan` 打印的网址，点点点就是验收；
  只有双方都看过，才谈得上推生产。

## 五、前端 Agent 工作地图（从任务到验证）

这一节是给维护 Agent 的最短路由，不是第二份完整文件清单。路径的唯一正本仍是 `README.md` § Maintenance Map；这里只回答“接到这类前端任务，先从哪里进去”。

### 先从任务进

| 你要做的事 | 第一入口 | 接着确认 | 改完怎样验 |
|---|---|---|---|
| Admin 页面布局、文案、交互 | 对应的 `admin/src/views/*.vue` 或子面板 | `AppShell.vue` 、`tokens.css` 、该页面的 API 文件 | `cd admin && npm run test:e2e`；改布局再做 390px 实拍 |
| Admin 数据、表单、列表行为 | 对应的 `admin/src/api/<domain>.ts` 和页面 | `gateway_admin_routes.py` 与对应的 service/store，再读该功能的现行文档 | 相关 pytest + `cd admin && npm run test:e2e` |
| Admin 全局皮肤、明暗场、演示数据 | `admin/src/theme/` 、`admin/src/demo/` 、`AppShell.vue` | 不要在视图内自建颜色总闸，演示适配器也只能在 `demo/` | Admin build + 对应页面 smoke；颜色改动做两种主题检查 |
| PWA 聊天、流式、会话交接 | `pwa/src/App.vue` 与对应的 `api/` 、`session/` 、`stream/` | `shenyu_gateway/chat_pipeline.py` 、`streaming.py` 与 `REQUEST_CONTEXT.md` 外部前端契约 | `cd pwa && npm test && npm run build`；用户可见修复还要做手机验收 |
| Memory Graph、Stars、Mem、Room 的前端表面 | 对应页面和其子目录（如 `views/memory-graph/`、`views/stars/`、`views/room/`） | 各自的 API 文件、后端功能包和 `MEMORY_ROOM.md` | 相关 pytest + Admin E2E；记忆网络布局还要看手机 |
| 家里地图、施工簿的 Admin 界面 | `ProjectMapBookModal.vue` 与 `bookshelf/` 下的子面板 | `admin/src/api/books.ts` 、`project_map.py` 、`project_delivery.py` 和 README/DOCS_MAP 权威源 | `tests/test_project_map.py` + `tests/test_owner_project_map.py` + Admin smoke |

### 一条最短链

`Vue 页面/子面板 → admin/src/api 契约 → FastAPI route/service → 现行文档 → pytest/E2E/手机验收`

如果这条链中间出现两个“谁都像在负责”的文件，先以页面的 API 契约和后端路由为准，不根据组件名猜责任。

### 共享文件的边界

- `admin/src/theme/tokens.css` 只守全站设计 token；单个页面的视觉差异留在自己的 scoped style。
- `admin/src/components/AppShell.vue` 只守全局壳、导航和主题按钮；业务页面不把交互塞回壳里。
- `admin/src/api/http.ts` 是请求总闸；域名 API 函数留在各自 `api/*.ts`，页面不直接拼 axios 请求。
- `pwa/src/App.vue` 只做界面状态与编排；会话、SSE 和持久化契约分别留在 `session/` 、`stream/` 和 `api/` 。

### 最近经验放在哪里

`project_delivery_log.jsonl` 的 `lesson` 只记已做完并有验证证据的可复用经验；前端地图不另建 TODO 或未来想法清单。代码、现行文档和测试仍是当前事实源；只在续接近期功能、排查近期回归或遇到反直觉取舍时，按 README 产品对象查看最近交付，普通任务不预读施工簿。已确认的故障经验则沿 `DEBUGGING_GUIDE.md` 引用。

### 视觉拥有者

| 路径 | 拥有 |
|---|---|
| `admin/src/theme/tokens.css` | 全部设计 token（昼夜两套）；颜色的唯一总闸 |
| `admin/src/theme/theme.ts` | 昼夜切换（`<html> data-theme` + localStorage） |
| `admin/src/components/AppShell.vue` | 全局壳：页眉、昼夜按钮、在线圆点、naive-ui 昼场皮肤 |
| `admin/src/demo/` | 演示数据与拦截适配器（`?demo=1` 的唯一实现） |
| `admin/scripts/mobile-shots.mjs` | 手机视口截图验收 |
| `admin/src/views/memory-graph/` | 记忆网络的皮肤（金、软木板、纸片家族 `OriginalPaper`、想起板 `RecallBoard`、阅读层 `AnchorOriginalsOverlay`、手绘符号 `SyGlyph`） |
| `admin/src/views/bookshelf/ProjectMapDeliveryPanel.vue` | 《家里地图》的施工簿：日期轴、产品筛选、交付状态、展开证据与经验块 |
| `admin/src/views/HomeView.vue` | 首页大卡与 bento 格子 |

新增独立维护的前端边界时，同步这份表 + `README.md` § Maintenance Map。
