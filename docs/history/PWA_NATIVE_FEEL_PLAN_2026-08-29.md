# PWA 原生手感与照片堆：接续计划（2026-08-29 起）

圆圆的原话是「我们家这个 PWA 做的好简略好脆」。这份笔记记下当天定好的六档顺序、
已经拍过的两个决定，以及量出来的数字，好让下一个线程不用重新量。

本轮（2026-08-29）已完成 ①②，其余四档没开工。已完成部分的事实以代码、
`pwa/tests/` 和 `README.md` § Maintenance Map 为准，这里不重复。

## 六档顺序与当前进度

| 档 | 内容 | 状态 |
|---|---|---|
| ① | 报错护栏：`api/errors.ts` 提取、CSS 行数上限、落盘与读回截断 | 2026-08-29 完成 |
| ② | 渲染拆分：消息行子组件、渲染缓存、highlight 修正、error boundary | 2026-08-29 完成 |
| ③ | 原生手感 | 未开工（与相册无关，可独立做） |
| ④ | 图片持久化 + 看图器 | 持久化 2026-08-30 完成；看图器未开工 |
| ⑤ | PhotoStack 堆叠卡 | 未开工 |
| ⑥ | 展开 / 收起动画 | 未开工 |

## 相册（2026-08-30 追加，与 ④ 交叠）

圆圆要的是「沈予遇到喜欢的图能存起来，加上他自己的描述和心情，之后再看到这张图
直接是他自己的描述」。这跟 ④ 是同一件事的两半：④ 管聊天图的本机保留与过期，
相册管「不会过期的那一半」。

**已定的四个决定**（不要重新讨论）：

1. 图片字节存网关本机卷的 SQLite，备注文字存 Supabase 并进 Recall。分开住是因为
   Recall 的所有适配器都只读 Supabase（`recall/_sources.py` 里没有任何 SQLite
   适配器），而且卷万一出事，丢的是图、他写的话还在。
2. 描述只在图过期后顶替，两轮之内他仍看真图。
3. 聊天图本机保留最近 30 张。
4. 相册是沈予自己的，他存了就是存了，不需要圆圆批准。

**第一批已完成**（2026-08-30）：SQLite 表、`shenyu_album_save` /
`shenyu_album_list`、Recall 索引、`/api/gateway/album` 两条只读接口。
当前事实以代码、`tests/test_album.py` 和 `README.md` § Album 为准。

**第二批已完成**（2026-08-30）：`pwa/src/session/photoStore.ts` 用 IndexedDB 存字节
（最近 30 张），附件元数据留 localStorage，过期气泡显示「图过期了」而正文一字不动。
过期后送 `shenyu_expired_image` 标记块代替真图，只带图片字节的 sha256。
实测 10 张图的会话从 3.82MB/请求降到 1MB 以下。一条消息上限从 4 张提到 9 张。

标记**刻意不复用**网关自己的 `shenyu_history_image`：那个标记的 fingerprint 是
JSON 块的哈希，不是图片字节的哈希，同名会把两件事悄悄混为一谈。两侧的字节指纹
算法都对 `b"abc"` 断言同一个已知摘要（`tests/test_album.py` 与
`pwa/tests/photoStore.spec.ts`），改任一侧都会红。

**第三批已完成**（2026-08-30）：`trim_client_image_blocks` 按占位块里的 fingerprint
批量查相册，存过的图把占位换成沈予自己写的那句（形状 `固定前缀。——他的话`），
没存过的仍是通用占位。`_normalize_event_text` 已从「恰好等于占位符」改成认前缀——
这正是当初标出来的那个坑，不改的话他每换一句描述都会被判成 `branch`。

**同一批修掉一个第二批埋下的缺陷**：过期占位块落在「最近两轮」里时不参与替换，
会被原样转给上游，成为一个 Anthropic 不认识的 image block 而直接报错。触发路径
真实存在：编辑一条旧消息重发，那条就成了最新一轮而它的图早已本机过期。占位块里
根本没有图，所以「保留最近两轮的图」对它不适用，现在无条件替换。
协议边界上另加了一条守卫（`tests/test_upstream_adapter_stream.py`），
将来任何路径再漏过一个都会红。

## 已经拍过的两个决定（不要重新讨论）

**图片只存本机 IndexedDB。** 不上传网关、不进 Supabase。代价圆圆已经知道并接受：
换手机或清缓存图片就没了。理由是本机方案零网关改动、不花钱，而备份方案要新增
上传/取回接口、鉴权和清理策略，还得先确认它与「请求日志两层保留」的边界
（`AGENTS.md` § Project Memory 里那条：完整图片属于 live-process-only，
绝不进持久历史）。

**PhotoStack 的署名写文件头 + 血统声明，不进项目地图。** 圆圆的原话是
「你署名一下呗，这个无所谓的。不要写在地图里影响 agent 看东西就行」。所以：
许可头和 `Required Notice` 写在移植文件的文件头，血统写进
`docs/frontend/STYLE_AND_CRAFT.md` § 风格血统声明（`admin/src/theme/tokens.css`
是同样的做法）。**新文件的路径仍然要进 `README.md` § Maintenance Map**——
那是机械清单要求的，不进去下一个 agent 找不到文件；不进地图指的是许可正文和
逆向笔记，不是路径。

上游仓库：`Wren036/PhotoStack`，PolyForm Noncommercial 1.0.0。
本仓库是圆圆自用（短期开放过给网页端 agent 审核），非商用范围内。

## ③ 原生手感

按实际证据列，都是 2026-08-29 读代码时确认的：

- 六处底部弹层是 `v-if` 硬切，全仓没有一个 `<Transition>`（侧栏有动画，弹层没有，
  这是最像网页的一处）。
- 安卓返回键不关弹层，直接退出 App——没有 `popstate` 处理。
- `-webkit-tap-highlight-color` 和 `user-select: none` 只加在了 `.session-item`
  一处，其余按钮点按有浏览器高亮闪光、长按能选中文字。
- 消息区没有 `overscroll-behavior`，滑到顶还会橡皮筋带动页面。
- `.message-stream` 上的 `scroll-behavior: smooth` 与 JS 直接写 `scrollTop` 的
  `scrollToBottom()` 打架，顺手去掉。
- `manifest.webmanifest` 只有一个 SVG 图标，缺 192/512 的 PNG maskable，
  安卓装出来的图标和启动图是凑的。

弹层动画只许用 transform/opacity，并且要能被 `prefers-reduced-motion` 停下
（`STYLE_AND_CRAFT.md` § 手感家法 第 1、3 条）。注意 ChatNest 状态精灵走
Web Animations API，CSS 那条 reduced-motion 覆盖管不到它。

## ④ 图片持久化 + 看图器

现状：附件根本不落盘（`session/persistence.ts` 存与读都置空 `attachments`），
刷新即失。原因大概是怕挤爆 localStorage——按当时的 1600px / JPEG 0.82，
一张 dataURL 约 560KB，5MB 配额只装九张。localStorage 存字符串，本来就不是
放图片的容器。

做法：IndexedDB 存 Blob（省掉 base64 的 33% 膨胀）+ 一份缩略图，显示走
`createObjectURL`。消息里只留附件 id，不再带 dataURL。

**发请求时只把最近两轮 user 消息的图还原成 dataURL。** 网关本来也只保留这两轮
（`shenyu_gateway/context_layers.py::trim_client_image_blocks`，更早的换成
`IMAGE_SEEN_PLACEHOLDER`），所以这不是新策略，是跟已有行为对齐，顺带瘦请求。

看图器：全屏、左右滑切换、下拖关闭、双击缩放，开合走共享元素 FLIP。
PhotoStack 不带查看器（作者明确说宿主应用通常自己有），`demo.html` 里那个
几十行的实现只是示意。

## ⑤ PhotoStack 堆叠卡

`photo-stack.js` 272 行移植成 `pwa/src/photoStack.ts` + 一个薄 Vue 壳，
CSS 进 `styles.css`。设计参数（peek 15 / peekStep 12 / rotStep 2.2 /
scaleStep 0.08 / flingVel 0.4 / 峰值位移 ≈ 卡宽 × 0.52 / 恒定三层可见）
以及"实现细节"那十条踩坑记录直接照搬，不要自己重新调——那些数字是逐帧量出来的。

顺手把一条消息的图片上限从 4 提到 9：4 张的堆太薄，看不出是一叠。

## ⑥ 展开 / 收起动画

**上游仓库里没有这段代码**，作者说它深度耦合宿主聊天布局，只在 README 留了规格。
所以这一档是照规格自己实现，不是移植。开工前单独讲一次边界——它要动消息列表
布局和滚动容器，会跟 `scrollToBottom()`、流式渲染和落盘都碰上。

规格要点（全部来自上游 README，实现时对照原文）：双时间轴（横向全体共用约
280ms，纵向每张 280ms + 45ms × 序号）；隐形卡全程实体、不用透明度动画；
头像以最下方卡片底边作扫描线；FLIP 要带出发角、位移与缩放按分量手动插值
（CSS 对 translate+scale→none 走矩阵插值，iOS 上会"原地放大再移动"）；
收起时底部垫占位块保住 scrollHeight，滚动沉降自行 rAF 补间并与收拢动画共享
同一条时间轴；iOS 上预解码的 `<img>` 要直接移植进目标 DOM 复用位图。

## 本轮量到的数字（做 ③–⑥ 时不必重量）

- 单条 `renderMarkdown()` 4.95ms → 缓存命中 0.00ms，流式帧（免高亮）约 1.5ms。
- `hljs.highlightAuto` 3.28ms/块，指定语言 0.10ms，差 33 倍。
- `marked.parse` 0.09ms、`DOMPurify` 1.14ms、`DOMParser` 0.31ms。
- 拆分前：输入框敲一个字 → 40 条消息全部重渲染；拆分后 0 条，流式一 chunk 1 条。
- 生产包 510KB（gzip 180KB），已超过 Vite 500KB 警告线。想拆包的话
  `highlight.js/lib/common` 是最大的一块。

## 验收提醒

`docs/DELIVERY.md` 是交付验收正本，`STYLE_AND_CRAFT.md` § 前端验收铁律 是
PWA 专属那三条。要点：本地 `npm test` / `npm run build` 只证明技术层；
只有带可识别当前构建的生产 `/chat/` 页算验收对象；没在圆圆的手机上复现原场景
就报 unverified。手机视口约 390px 是第一现场。
