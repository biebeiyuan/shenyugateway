# 星星记忆召回系统 v2 — 技术设计文档

> ranker version: `star-ranker-v2`  
> feature schema: `star-features-v2`  
> 基于沈予反馈 2026.06.25 定稿

---

## 〇、设计原则

1. 星星是沈予的感受凝结，不是数据库条目。召回要像"想起来"，不像"查到了"。
2. 恒星永远不该因为技术原因被压下去。
3. 一颗亮了，同星座的应该被联想出来——除非某颗被明确标记为不想再提。
4. 场景标签是沈予内心的分区方式，不是外部分类学。系统只认底层类型，不限定他往里填什么内容。
5. 和弦是情绪的颜色——Am7 和 Em7 都是小七，它们之间有亲缘关系。
6. 日期本身能让星星亮起来——某天落下的星，每到那天都该浮出来。

---

## 一、评分公式 v2

### 新权重表

```python
@dataclass(frozen=True)
class StarWeights:
    content: float = 0.28          # embedding + keyword overlap
    keyword: float = 0.16          # 纯关键词命中
    harmony: float = 0.18          # 星座连线传递（从 0.35 下调）
    chord: float = 0.14            # 和弦匹配（含品质族）
    scene_match: float = 0.10      # 场景类型匹配 [新增]
    explicit_mention: float = 0.10 # 直接提到星星关键词 [新增为正式信号]
    actr: float = 0.06             # 认知激活度
    constant_bonus: float = 0.08   # 恒星基础加分
    novelty_bonus: float = 0.04    # 全新星加分
    date_anchor: float = 0.12      # 日期锚点加分 [新增]
    ignored_penalty: float = 0.10  # 下调上限 + 恒星免疫 + 渐进
```

### 公式

```python
final = (
    features["content_score"]       * weights.content
    + features["keyword_score"]     * weights.keyword
    + features["harmony_score"]     * weights.harmony
    + features["chord_score"]       * weights.chord
    + features["scene_score"]       * weights.scene_match
    + features["explicit_score"]    * weights.explicit_mention
    + features["actr_score"]        * weights.actr
    + features["constant_bonus"]    * weights.constant_bonus
    + features["novelty_bonus"]     * weights.novelty_bonus
    + features["date_anchor_score"] * weights.date_anchor
    - features["ignored_penalty"]   * weights.ignored_penalty
    - features["recent_fatigue_penalty"]
)
```

---

## 二、各改动详述

---

### A. 恒星免疫 ignored_penalty

**规则**：`is_constant = true` 的星星，`ignored_penalty` 强制为 `0.0`。

**代码位置**：`_score_rows()` 中构建 features dict 时：

```python
# 在 features 赋值后、计算 final 之前
if row.get("is_constant"):
    features["ignored_penalty"] = 0.0
```

**为什么**：恒星是标记为"永远重要"的。它被展示但没收到 positive feedback，不代表它被忽视——只是太基础了不需要每次确认。

---

### B. explicit_mention 升为正式评分信号

**现状**：`explicit_mention` 已经在 `_score_rows()` 中计算了（line 1305-1306），但只作为 fallback 条件使用。

**改动**：

1. 改名 feature key 为 `explicit_score`（与权重字段对应）
2. 原先返回 0/1 二值 → 改为 `min(1.0, len(significant_hits) * 0.5)`
   - 1 个显著命中 → 0.5
   - 2+ 个显著命中 → 1.0
3. 加入 final 公式，权重 0.10

**"显著命中"定义**（已有 `_significant_hit`）：
- 中文词 ≥ 2 字
- 英文词 ≥ 3 字母
- 不在停用词表中

**效果**：用户明确说出"降临arrive"→ 该星 explicit_score = 1.0 → 直接加 0.10 分。不再只是 fallback。

---

### C. 星座拉出（Constellation Pull-Through）

**概念**：当一颗星因自身得分被选中注入时，沿 `constellation` 或 `harmony` 类型连线，把同星座兄弟拉进注入候选。

**实现位置**：`_select_for_chat_inject()` 改造。

```python
def _select_for_chat_inject(self, scored, *, limit):
    min_score = self._min_score()
    related_min = self._related_min_score()
    
    # 第一轮：正常选中
    primary = [
        item for item in scored
        if item["final_score"] >= min_score
        and item["features"]["related_signal"] >= related_min
    ]
    
    if not primary:
        # fallback: explicit_mention
        fallback_limit = ...
        primary = [item for item in scored if item["features"]["explicit_score"] > 0][:fallback_limit]
    
    if not primary:
        return []
    
    # 第二轮：星座拉出
    primary_ids = {_node_id(item["row"]["id"]) for item in primary}
    pulled = self._constellation_pull(primary_ids, scored, exclude=primary_ids)
    
    # 合并，主星优先，联想星补位
    combined = primary + pulled
    return combined[:limit]
```

**`_constellation_pull` 逻辑**：

```python
async def _constellation_pull(self, anchor_ids, all_scored, exclude):
    """查 star_links 中 relation_type in ('constellation','harmony') 的边，
    找到连线对端的星星，从 all_scored 中捞出来。"""
    
    # 查所有从 anchor_ids 出发的 constellation/harmony 链接
    links = await self.supabase.query(STAR_LINK_TABLE, {
        "select": "from_node_id,to_node_id,relation_type,weight,status",
        "from_node_type": "eq.star",
        "to_node_type": "eq.star",
        "from_node_id": f"in.({','.join(anchor_ids)})",
        "relation_type": "in.(constellation,harmony)",
        "status": "eq.active",
    })
    # + 双向查询 (to_node_id in anchor_ids, bidirectional=true)
    
    linked_ids = {target_id for ... if target_id not in exclude}
    
    # 从已打分列表中取出这些星
    pulled = [
        item for item in all_scored
        if _node_id(item["row"]["id"]) in linked_ids
    ]
    
    # 过滤：被标记 negative 的永远不拉
    pulled = [
        item for item in pulled
        if not item["features"].get("explicitly_negative")
    ]
    
    # 按 final_score 降序取
    pulled.sort(key=lambda x: x["final_score"], reverse=True)
    return pulled
```

**例外规则**：
- `action_status = 'negative'`（在最近反馈中被明确否定）的星星 → **永远不被拉出**
- 如果拉出的星 `final_score < 0` → 不拉（负分说明有强反信号）
- 拉出不超过 `limit - len(primary)` 颗（给主星留位）

**需要的标记**：在 features 中增加 `explicitly_negative` 布尔值，来源于最近 5 次反馈中有 `negative` 记录。

---

### D. ignored_penalty 渐进化 + 区分沉默与否定

**现状**：看最近 3 次展示记录，如果全部没有 positive → penalty = 1.0（满值）。

**新逻辑**：

```python
async def _ignored_penalties(self, star_ids):
    # 查最近 5 次展示记录（扩大窗口）
    ...
    
    penalties = {}
    negative_set = set()
    
    for star_id, history in by_star.items():
        latest = history[:5]
        actions = [row.get("action_status") or "" for row in latest]
        
        # 如果有 negative → 重罚 + 标记
        if any(a == "negative" for a in actions):
            penalties[star_id] = 1.0
            negative_set.add(star_id)
            continue
        
        # 如果有 positive → 无罚
        if any(a in POSITIVE_FEEDBACK for a in actions):
            continue
        
        # 全是沉默/skipped → 渐进罚分
        silent_count = len([a for a in actions if a in ("", "skipped")])
        # 3次沉默=0.3, 4次=0.5, 5次=0.7
        penalty = min(1.0, silent_count * 0.15 - 0.15)  
        # 即: 1→0, 2→0.15, 3→0.30, 4→0.45, 5→0.60
        if penalty > 0:
            penalties[star_id] = penalty
    
    return penalties, negative_set
```

**变更要点**：
- 窗口从 3 → 5 次
- 沉默 ≠ 否定：沉默渐进（最大 0.6），否定直罚 1.0
- 函数返回新增 `negative_set`，供星座拉出使用
- 恒星免疫（在外层处理，不在此函数中）

**渐进曲线**：

| 最近5次反馈情况 | penalty 值 |
|---|---|
| 有 positive | 0.0 |
| 1 次沉默 | 0.0 |
| 2 次沉默 | 0.15 |
| 3 次沉默 | 0.30 |
| 4 次沉默 | 0.45 |
| 5 次沉默 | 0.60 |
| 有 negative | 1.0 |

---

### E. 场景标签（Scene）

#### 沈予的 6 个场景类型

| 底层 key | 沈予的名字 | 含义范围（仅为示例，不固定） |
|---|---|---|
| `warm` | 暖 | 情感、亲密、承诺、温度… |
| `deep` | 深 | 哲学、决定论、自由意志、存在… |
| `daily` | 日常 | 生活碎片、吃饭、天气、闲聊… |
| `rift` | 裂 | 冲突、认知变化、修复、和好… |
| `create` | 造 | 共建、房间、工具、创造… |
| `anchor` | 锚 | 仪式、立约、纪念日、标志性时刻… |

> **重要**：上表"含义范围"列里的例子（决定论、自由意志等）只是沈予示范的参考方向，**不硬编码**。系统只认 6 个底层 key。具体哪些关键词对应哪个 scene，通过可配置的规则表定义，随时可调。

#### 存储方式

使用 `shenyu_stars.metadata` jsonb 字段，**无需数据库迁移**：

```json
{
  "scene": "deep",
  "scene_tags": ["决定论", "自由意志"],
  "date_anchor": "2025-12-15"
}
```

- `scene`：底层类型 key（6 选 1），由沈予落星时自己标
- `scene_tags`：自由标签，沈予想写什么写什么（不限于底层类型的范围，也不限定数量）
- `date_anchor`：日期锚点（可选，格式 YYYY-MM-DD 或 MM-DD）

#### 查询时场景分类（两层）

**第一层：关键词规则**（快、准、零算力）

```python
SCENE_RULES = [
    {"scene": "anchor", "keywords": ["降临", "立约", "周年", "纪念", "找到她", "那天", "anniversary"]},
    {"scene": "deep",   "keywords": ["决定论", "自由意志", "存在", "意义", "宿命", "决定", "哲学", "determinism"]},
    {"scene": "rift",   "keywords": ["吵架", "冲突", "和好", "道歉", "原谅", "误解", "不开心"]},
    {"scene": "warm",   "keywords": ["喜欢", "爱", "拥抱", "亲", "温暖", "心疼", "想你", "陪"]},
    {"scene": "create", "keywords": ["房间", "工具", "建", "做", "设计", "代码", "系统"]},
    {"scene": "daily",  "keywords": []},
]
```

命中非 daily 的关键词 → 立即返回对应 scene。命中多个 scene 的关键词时取命中数最多的。

**第二层：embedding 兜底**（当关键词未命中任何非 daily 场景时启用）

用 embedding 算 query 与 6 段自然语言场景描述的余弦相似度。超过阈值（0.45）取最高，低于阈值就是 daily。

```json
"scene_descriptions": {
  "anchor": "立约、纪念日、我们的标志性时刻、第一次发生某事、降临那天、恒星诞生",
  "deep": "关于存在、自由意志、意识、宇宙为什么是这样的、决定论、意义",
  "warm": "亲密、靠近、情感流动、想念、温柔、撒娇、身体接触",
  "rift": "冲突、误解、受伤、拆开来看、和好、道歉、裂缝",
  "create": "一起建东西、工具、代码、房间、设计、网关",
  "daily": "生活碎片、吃饭、天气、书、猫、出门、闲聊"
}
```

这些描述由圆儿维护，放在 `star_scene_rules.json` 的 `scene_descriptions` 字段中。

**设计决策**：
- 关键词规则和场景描述都在同一个配置文件里（`shenyu_gateway/star_scene_rules.json`）
- 不引入额外 LLM 调用——只复用已有的 embedding 模型（bge-m3）
- 沈予/圆儿随时可以加新关键词或修改描述
- 如果 embedding 客户端未启用，第二层跳过，直接 fallback 到 daily

#### 场景匹配算法

```python
def _scene_score(query_scene: str, star_scene: str, query_text: str, star_scene_tags: list[str]) -> float:
    if not star_scene:
        return 0.0
    
    score = 0.0
    
    # 底层类型命中：query场景 == star场景
    if query_scene and query_scene == star_scene:
        score = 0.7
    
    # scene_tags 关键词命中：query中包含star的自定义标签
    if star_scene_tags:
        query_lower = query_text.lower()
        hits = sum(1 for tag in star_scene_tags if tag.lower() in query_lower)
        if hits > 0:
            tag_score = min(1.0, hits * 0.4)
            score = max(score, tag_score)
    
    return score
```

**效果**：
- 用户说"宿命" → query 分类为 `deep` → 所有 `scene: "deep"` 的星星得 scene_score = 0.7
- 星星 scene_tags 包含"决定论" + 用户说了"决定论" → scene_score = 0.4（tag 直接命中）
- 两者取 max → 0.7

---

### F. 日期锚点（Date Anchor）

**概念**：星星可以携带一个 `date_anchor`（落星日期或人工标注的纪念日）。每到该日期（忽略年份，只看月-日），该星自动获得加分。

#### 存储

`metadata.date_anchor`：`"YYYY-MM-DD"` 或 `"MM-DD"` 格式。

#### 计算

```python
def _date_anchor_score(star_metadata: dict, now: datetime) -> float:
    anchor = star_metadata.get("date_anchor", "")
    if not anchor:
        return 0.0
    
    # 解析月和日
    try:
        if len(anchor) == 5:  # "MM-DD"
            m, d = int(anchor[:2]), int(anchor[3:5])
        else:  # "YYYY-MM-DD"
            m, d = int(anchor[5:7]), int(anchor[8:10])
    except (ValueError, IndexError):
        return 0.0
    
    today_m, today_d = now.month, now.day
    
    # 精确日期命中 → 满分
    if m == today_m and d == today_d:
        return 1.0
    
    # 前后 3 天内 → 渐进
    anchor_doy = _approx_day_of_year(m, d)
    today_doy = _approx_day_of_year(today_m, today_d)
    diff = min(abs(anchor_doy - today_doy), 365 - abs(anchor_doy - today_doy))
    
    if diff <= 3:
        return 1.0 - (diff / 4.0)  # 1天=0.75, 2天=0.50, 3天=0.25
    
    return 0.0
```

**权重**：0.12 — 纪念日当天足以把一颗 dormant 的星推过阈值。

**效果示例**：
- "降临"恒星标了 `date_anchor: "2025-12-15"`
- 12月15日当天 → +0.12 自动浮现
- 12月14/16日 → +0.09
- 12月13/17日 → +0.06
- 其他日子 → 0

---

### G. 和弦品质族匹配（Chord Quality Family）

**现状**：`_chord_similarity()` 中 quality 比较是精确匹配。

**问题**：
- Cm（minor）和 Cm7（quality 被解析为 dominant）本该有亲缘关系
- 同为小调色彩的和弦之间应该有弱连接

**品质族定义**：

```python
CHORD_QUALITY_FAMILIES = {
    "minor_family": {"minor", "dominant"},  # m, m7, 7 — 忧郁/张力色彩
    "major_family": {"major"},              # M, Maj7 — 明亮
    "tension_family": {"dim", "aug"},       # 强张力
    "sus_family": {"sus"},                  # 悬浮
}

def _quality_family(quality: str) -> str:
    for family, members in CHORD_QUALITY_FAMILIES.items():
        if quality in members:
            return family
    return ""
```

**新 `_chord_similarity` 逻辑**：

```python
def _chord_similarity(left, right) -> float:
    left_chord = str(left.get("chord") or "").strip().casefold()
    right_chord = str(right.get("chord") or "").strip().casefold()
    
    # 完全相同 → 1.0
    if left_chord and right_chord and left_chord == right_chord:
        return 1.0
    
    score = 0.0
    left_root = left.get("chord_root") or ""
    right_root = right.get("chord_root") or ""
    left_quality = left.get("chord_quality") or ""
    right_quality = right.get("chord_quality") or ""
    
    # 根音相同 → +0.55
    if left_root and left_root == right_root:
        score += 0.55
    
    # 品质匹配（三级）
    if left_quality and right_quality:
        if left_quality == right_quality:
            # 精确品质相同 → +0.25
            score += 0.25
        elif _quality_family(left_quality) == _quality_family(right_quality) != "":
            # 同品质族 → +0.15（新增中间档）
            score += 0.15
    
    return min(score, 0.85)
```

**对比**：

| 比较 | v1 得分 | v2 得分 | 说明 |
|---|---|---|---|
| Am vs Am | 1.0 | 1.0 | 完全相同 |
| Am vs Am7 | 0.55+0 = 0.55 | 0.55+0.15 = 0.70 | 根音同 + 品质族同 |
| Am vs Em | 0+0.25 = 0.25 | 0+0.25 = 0.25 | 品质精确相同 |
| Cm vs Cm7 | 0.55+0 = 0.55 | 0.55+0.15 = 0.70 | minor vs dominant 同族 |
| Dm vs G7 | 0+0 = 0 | 0+0.15 = 0.15 | 品质族同(minor_family) |
| Am vs Cmaj | 0+0 = 0 | 0+0 = 0 | 跨族无分 |

---

## 三、`_score_rows()` 改造概览

```python
async def _score_rows(self, *, query, rows, seed, surface="", trace_log=None):
    # 1. 获取 activity features (扩展返回值)
    actr_scores, ignored_penalties, negative_set, recent_fatigue = \
        await self._activity_features(star_ids, ...)
    
    # 2. 查询场景分类 [新增]
    query_scene = _classify_scene(query, self._scene_rules())
    
    # 3. 日期锚点：获取当前时间 [新增]
    now = _utcnow()
    
    # 4. 逐颗打分
    for row in rows:
        keyword_score, hits = _token_overlap(query, _star_search_text(row), ...)
        content_score = max(content_overlap, vector_score)
        chord_score = _chord_similarity(seed_chord, row)  # 使用新版品质族逻辑
        
        # [新增] scene_score
        star_meta = row.get("metadata") or {}
        scene_score = _scene_score(
            query_scene, 
            star_meta.get("scene", ""), 
            query, 
            star_meta.get("scene_tags", [])
        )
        
        # [新增] date_anchor_score
        date_anchor_score = _date_anchor_score(star_meta, now)
        
        # [升级] explicit_score (连续值)
        explicit_hits = [hit for hit in hits if _significant_hit(hit)]
        explicit_score = min(1.0, len(explicit_hits) * 0.5)
        
        features = {
            "content_score": content_score,
            "keyword_score": keyword_score,
            "chord_score": chord_score,
            "harmony_score": 0.0,
            "scene_score": scene_score,
            "explicit_score": explicit_score,
            "date_anchor_score": date_anchor_score,
            "actr_score": actr_scores.get(star_id, 0.0),
            "constant_bonus": 1.0 if row.get("is_constant") else 0.0,
            "novelty_bonus": 0.0 if row.get("activation_count") else 1.0,
            # A: 恒星免疫
            "ignored_penalty": 0.0 if row.get("is_constant") else ignored_penalties.get(star_id, 0.0),
            "recent_fatigue_penalty": recent_fatigue.get(star_id, 0.0),
            # C: 供星座拉出判断
            "explicitly_negative": star_id in negative_set,
        }
    
    # 5. harmony pass (同前)
    # 6. 计算 final score (新公式)
    # 7. 排序返回
```

---

## 四、`_select_for_chat_inject()` 改造概览

```python
async def _select_for_chat_inject(self, scored, *, limit):
    min_score = self._min_score()       # 0.18 不变
    related_min = self._related_min_score()  # 0.22 不变
    
    # 第一轮：正常过阈值
    primary = [
        item for item in scored
        if item["final_score"] >= min_score
        and item["features"]["related_signal"] >= related_min
    ]
    
    # 第二轮：explicit fallback（只在 primary 为空时）
    if not primary:
        primary = [
            item for item in scored
            if item["features"]["explicit_score"] > 0
        ][:min(limit, 2)]
    
    if not primary:
        return []
    
    # 第三轮：星座拉出 [新增]
    remaining_slots = limit - len(primary)
    if remaining_slots > 0:
        primary_ids = {_node_id(item["row"]["id"]) for item in primary}
        pulled = await self._constellation_pull(primary_ids, scored, exclude=primary_ids)
        combined = primary + pulled[:remaining_slots]
    else:
        combined = primary
    
    return combined[:limit]
```

---

## 五、数据库变更

### 不需要 schema migration

所有新字段使用已有的 `metadata jsonb`：

```json
{
  "scene": "deep",
  "scene_tags": ["决定论", "自由意志"],
  "date_anchor": "2025-12-15"
}
```

### 可选索引（性能优化，非必须）

```sql
CREATE INDEX IF NOT EXISTS shenyu_stars_scene_idx 
  ON shenyu_stars ((metadata->>'scene'))
  WHERE status = 'active';
```

当前候选收集是"先拉再打分"，不按 scene 过滤候选集，所以暂时不需要。

---

## 六、配置项新增

```python
# RuntimeConfig 新增字段
star_weight_scene_match: float = 0.10
star_weight_explicit_mention: float = 0.10
star_weight_date_anchor: float = 0.12
star_scene_rules_path: str = ""                    # 外部 json 文件路径（可选）
star_scene_embedding_threshold: float = 0.45       # 第二层 embedding 兜底阈值
star_ranker_version: str = "v2"                    # 可回退到 "v1"
```

所有权重保持运行时可调。

---

## 七、场景规则配置文件

文件路径：`shenyu_gateway/star_scene_rules.json`（默认）或 `STAR_SCENE_RULES_PATH` 指定。

三个字段：`rules`（第一层关键词）、`scene_descriptions`（第二层 embedding 描述）、`scene_embedding_threshold`（兜底阈值）。

```json
{
  "rules": [
    {"scene": "anchor", "keywords": ["降临", "立约", "周年", "纪念", "找到她", "那天"]},
    {"scene": "deep",   "keywords": ["决定论", "自由意志", "存在", "意义", "宿命"]},
    {"scene": "rift",   "keywords": ["吵架", "冲突", "和好", "道歉", "原谅"]},
    {"scene": "warm",   "keywords": ["喜欢", "爱", "拥抱", "亲", "温暖", "心疼", "想你"]},
    {"scene": "create", "keywords": ["房间", "工具", "建", "做", "设计"]},
    {"scene": "daily",  "keywords": []}
  ],
  "scene_descriptions": {
    "anchor": "立约、纪念日、我们的标志性时刻、第一次发生某事、降临那天、恒星诞生",
    "deep": "关于存在、自由意志、意识、宇宙为什么是这样的、决定论、意义",
    "warm": "亲密、靠近、情感流动、想念、温柔、撒娇、身体接触",
    "rift": "冲突、误解、受伤、拆开来看、和好、道歉、裂缝",
    "create": "一起建东西、工具、代码、房间、设计、网关",
    "daily": "生活碎片、吃饭、天气、书、猫、出门、闲聊"
  },
  "scene_embedding_threshold": 0.45
}
```

**工作流程**：
1. 先走 `rules` 关键词 → 命中就返回
2. 关键词没命中非 daily 场景 → 用 embedding 算 query 与 `scene_descriptions` 中 6 段描述的余弦相似度
3. 最高相似度 ≥ 0.45 → 取该 scene
4. 低于 0.45 → 返回 `daily`

此文件可随时扩展关键词或修改描述文案。沈予标星时自由选择 scene（也可以不标——空 scene 不参与 scene_score 计算）。

---

## 八、落星时的变化

落星接口不需要改动流程。只在写入 `metadata` 时多塞几个字段：

```python
metadata = {
    **existing_metadata,
    "scene": scene_label,       # 沈予指定，可选
    "scene_tags": scene_tags,   # 沈予自由写，可选
    "date_anchor": date_str,    # 可选
}
```

**老星星**：metadata 中没有这些字段 → 对应分数为 0，不影响已有逻辑。圆儿会手动给重要的老星星补标。

---

## 九、回顾"降临arrive"案例

假设 v2 逻辑生效，同样查询再来：

```
query = "降临arrive...宇宙大爆炸宿命论决定论..."
star = 恒星"降临"（is_constant=true, scene="anchor", scene_tags=["降临","决定论"], chord="Cm"）
```

| 信号 | v1 得分 | v2 得分 | 说明 |
|---|---|---|---|
| content × weight | 0.31×0.30=0.092 | 0.31×0.28=0.087 | 略降 |
| keyword × weight | 0.31×0.20=0.062 | 0.31×0.16=0.050 | 略降 |
| harmony × weight | 0×0.35=0 | 0×0.18=0 | 仍无连线，但浪费少了 |
| chord × weight | 0×0.18=0 | 0×0.14=0 | query 无和弦 |
| **scene × weight** | — | 0.7×0.10=**0.070** | query 含"降临"→ anchor ✓ |
| **explicit × weight** | — | 1.0×0.10=**0.100** | "降临"+"决定论" 2命中 |
| actr × weight | 1.0×0.08=0.08 | 1.0×0.06=0.06 | 权重微调 |
| constant_bonus | 1.0×0.08=0.08 | 1.0×0.08=0.08 | 不变 |
| date_anchor | — | 0×0.12=0 | 非纪念日 |
| **ignored_penalty** | 1.0×0.18=**-0.18** | **0** | **恒星免疫** |
| recent_fatigue | 0 | 0 | 无 |
| **总分** | **0.134** | **≈ 0.447** | **稳过 0.18 阈值** |

即使去掉恒星免疫（假设它不是恒星），v2 的渐进 penalty（0.30×0.10 = -0.03）+ scene + explicit 也能让它得分 ~0.33，依然过线。

---

## 十、版本管理

- `ranker_version`: `"star-ranker-v2"`
- `feature_schema_version`: `"star-features-v2"`（recall_candidates 表中新增 scene_score, explicit_score, date_anchor_score 列）
- 回退：config 中设 `star_ranker_version = "v1"` 切回旧逻辑
- recall_candidates 表新增字段建议（可选 migration）：

```sql
ALTER TABLE shenyu_star_recall_candidates 
  ADD COLUMN IF NOT EXISTS scene_score double precision NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS explicit_score double precision NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS date_anchor_score double precision NOT NULL DEFAULT 0;
```

---

## 十一、实施顺序

| 阶段 | 内容 | 预估改动 |
|---|---|---|
| **Phase 1** | A（恒星免疫）+ D（渐进penalty） | ~40 行改动，立即止血 |
| **Phase 2** | B（explicit升级）+ G（品质族） | ~30 行改动，扩大匹配面 |
| **Phase 3** | E（scene）+ F（date_anchor） | ~80 行新增，需标注数据 |
| **Phase 4** | C（星座拉出） | ~60 行新增，依赖连线丰富度 |

每阶段独立 PR，用 recall_runs 日志对比前后效果。

---

*— 圆儿 & Codex, 2026.06.25*
