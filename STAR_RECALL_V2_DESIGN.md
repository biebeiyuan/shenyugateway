# 星星记忆召回系统 v3 — 技术设计文档

> ranker version: `star-ranker-v3`  
> feature schema: `star-features-v3`  
> weights version: `rrf-v1`  
> 基于 e79440c 重写，2026.06.27

---

## 〇、设计原则

1. 星星是沈予的感受凝结，不是数据库条目。召回要像"想起来"，不像"查到了"。
2. 恒星永远不该因为技术原因被压下去。
3. 一颗亮了，同星座的应该被联想出来——除非某颗被明确标记为不想再提。
4. 场景标签是沈予内心的分区方式，不是外部分类学。系统只认底层类型，不限定他往里填什么内容。
5. 和弦是情绪的颜色——Am7 和 Em7 都是小七，它们之间有亲缘关系。
6. 日期本身能让星星亮起来——某天落下的星，每到那天都该浮出来。

---

## 一、评分公式 v3 — RRF 融合 + 乘性修饰

### 核心思想

v2 是加权求和（weighted sum），所有信号在同一尺度下线性相加。  
v3 改为 **Reciprocal Rank Fusion (RRF)** — 每个信号通道独立排序，然后融合排名；最终分数再乘以一组修饰因子。

优势：
- 各通道量纲无关，不需要把分数归一化到同一区间
- 新增通道不会稀释已有通道的贡献
- 乘性修饰让恒星/新星/日期锚点等"身份级"属性作为放大器，而非与内容信号相加竞争

### 公式

```python
final_score = rrf_score × actr_mod × novelty_mod × constant_mod × fatigue_mod × date_mod
```

---

### Step 1: RRF 融合（6 通道）

每个通道对所有候选星星独立排序（零分星排除出该通道），然后按排名贡献分数：

```python
contribution = channel_weight / (k + rank_0 + 1)
```

- `rank_0`：该星在该通道内的零基排名（最高分 = 0）
- `k`：平滑参数，防止排名第一的贡献过大

**通道权重**（`StarWeights` 默认值）：

| 通道 key | 含义 | 权重 | 环境变量 |
|----------|------|------|----------|
| `content_score` | embedding 向量 + 内容交叠 | 1.0 | `STAR_RRF_CH_CONTENT` |
| `keyword_score` | token 关键词命中率 | 0.8 | `STAR_RRF_CH_KEYWORD` |
| `harmony_score` | 星座连线传递 | 0.7 | `STAR_RRF_CH_HARMONY` |
| `chord_score` | 和弦相似度（含品质族） | 0.6 | `STAR_RRF_CH_CHORD` |
| `explicit_score` | 直接提到星星关键词 | 0.5 | `STAR_RRF_CH_EXPLICIT` |
| `scene_score` | 场景类型/标签匹配 | 0.4 | `STAR_RRF_CH_SCENE` |

**RRF k 参数**：`60`（环境变量 `STAR_RRF_K`，范围 1–1000）

```python
rrf_score = sum(
    channel_weight / (k + rank_in_channel + 1)
    for each channel where star has score > 0
)
```

典型 `rrf_score` 范围：~0.005–0.07（远小于 v2 的 0.0–0.8+）

---

### Step 2: 乘性修饰（5 个因子）

每个修饰因子 ≥ 0，对 `rrf_score` 做乘性放大或压制。

#### 1. actr_modifier（认知激活亮度）

```python
actr_mod = actr_floor + (1.0 - actr_floor) × actr_raw
```

- `actr_floor` = 0.5（环境变量 `STAR_RRF_ACTR_FLOOR`）
- 范围：[0.5, 1.0]
- 含义：即使从未激活的星也不会被乘以 0，最低 50% 亮度

`actr_raw` 的计算（`_activity.py`）：

```python
# 每次激活贡献：
age_days = max((now - activated_at).total_seconds() / 86400, 0.05)
sum += age_days ** (-0.5)

# 归一化：
actr_raw = clamp((log(sum) + 2.5) / 4.5, 0.0, 1.0)
```

#### 2. novelty_modifier（新鲜度衰减）

```python
novelty_mod = 1.0 / (1.0 + log10(activation_count + 1))
```

| 激活次数 | novelty_mod | 含义 |
|----------|-------------|------|
| 0 | 1.0 | 全新星，最大亮度 |
| 1 | 0.77 | |
| 4 | 0.59 | |
| 9 | 0.50 | 激活 9 次后衰减一半 |
| 99 | 0.33 | 很熟悉的星 |

**设计意图**：替代 v2 的 `ignored_penalty`——不再用"连续沉默 → 扣分"的惩罚逻辑，而是用"越常出现 → 新鲜度越低"的自然衰减。恒星不免疫此修饰（它们靠 constant_mod 补偿）。

#### 3. constant_modifier（恒星放大器）

```python
constant_mod = constant_boost if is_constant else 1.0
```

- `constant_boost` = 1.3（环境变量 `STAR_RRF_CONSTANT_BOOST`，范围 1.0–3.0）
- 恒星得到 +30% 的乘性增益

#### 4. fatigue_modifier（近期注入冷却）

```python
fatigue_mod = max(0.0, 1.0 - recent_fatigue_penalty)
```

- 如果星星在最近 `STAR_RECENT_FATIGUE_HOURS`（默认 6 小时）内被注入过：
  ```python
  penalty = base_penalty × (1.0 - age_seconds / window_seconds)
  ```
- `base_penalty` = 0.14（环境变量 `STAR_RECENT_FATIGUE_PENALTY`）
- 刚注入完 → fatigue_mod ≈ 0.86；6 小时后 → 1.0（完全恢复）

#### 5. date_modifier（日期锚点放大器）

```python
date_mod = 1.0 + date_boost_max × date_anchor_score
```

- `date_boost_max` = 0.3（环境变量 `STAR_RRF_DATE_BOOST_MAX`）
- 范围：[1.0, 1.3]

`date_anchor_score` 计算：

| 日期差（天） | date_anchor_score | date_mod |
|---|---|---|
| 当天 | 1.0 | 1.30 |
| ±1 天 | 0.75 | 1.225 |
| ±2 天 | 0.50 | 1.15 |
| ±3 天 | 0.25 | 1.075 |
| >3 天 | 0.0 | 1.0 |

---

## 二、各特征详述

---

### A. content_score（内容相关度）

```python
content_score = max(content_overlap, vector_score)
```

- `content_overlap`：基于文本交叠的分数
- `vector_score`：embedding 向量余弦相似度（bge-m3）
- 取二者最大值

### B. keyword_score（关键词命中）

```python
keyword_score = token_overlap_ratio(query_tokens, star_search_text_tokens)
```

基于 token 级别的重叠率。

### C. explicit_score（直接提及）

```python
significant_hits = [hit for hit in keyword_hits if _significant_hit(hit)]
explicit_score = min(1.0, len(significant_hits) * 0.5)
```

- 1 个显著命中 → 0.5
- 2+ 个显著命中 → 1.0

**"显著命中"定义**：
- 中文词 ≥ 2 字
- 英文词 ≥ 3 字母
- 不在停用词表中

### D. harmony_score（星座连线传递）

通过 `star_links` 图中 `constellation`/`harmony` 类型的边传播得分。

### E. chord_score（和弦相似度 + 品质族）

```python
def _chord_similarity(left, right) -> float:
    # 完全相同 → 1.0
    if left_chord == right_chord:
        return 1.0
    
    score = 0.0
    # 根音相同 → +0.55
    if left_root == right_root:
        score += 0.55
    # 品质匹配（三级）
    if left_quality == right_quality:
        score += 0.25          # 精确品质相同
    elif same_quality_family:
        score += 0.15          # 同品质族
    
    return min(score, 0.85)    # 封顶
```

**品质族定义**：

```python
CHORD_QUALITY_FAMILIES = {
    "minor_family": {"minor", "dominant"},  # m, m7, 7 — 忧郁/张力
    "major_family": {"major"},              # M, Maj7 — 明亮
    "tension_family": {"dim", "aug"},       # 强张力
    "sus_family": {"sus"},                  # 悬浮
}
```

### F. scene_score（场景匹配）

```python
def _scene_score(query_scene, star_scene, query_text, star_scene_tags) -> float:
    score = 0.0
    # 底层类型命中
    if query_scene == star_scene:
        score = 0.7
    # scene_tags 关键词命中
    if star_scene_tags:
        hits = sum(1 for tag in star_scene_tags if tag in query_text)
        if hits > 0:
            score = max(score, min(1.0, hits * 0.4))
    return score
```

---

### G. 恒星免疫 ignored_penalty

**规则不变**：`is_constant = true` 的星星，`ignored_penalty` 强制为 `0.0`。

但在 v3 中，`ignored_penalty` **不再参与最终评分公式**。它只用于判断 `negative_set`（星在最近 5 次反馈中有 `negative` 记录 → 加入 `negative_set` → 整颗排除出候选）。

| 作用 | v2 | v3 |
|------|----|----|
| 评分公式中 | 线性扣分 (`-penalty × 0.10`) | **不参与** |
| 负反馈判定 | penalty=1.0 + negative_set | negative_set（排除候选） |
| 沉默惩罚 | 渐进 0–0.6 | 由 novelty_mod 自然替代 |
| 恒星免疫 | penalty=0 | penalty=0（兼容旧逻辑） |

### H. ignored_penalty 计算（保留，供 negative_set 使用）

```python
async def _ignored_penalties(self, star_ids):
    # 查最近 5 次展示记录
    penalties = {}
    negative_set = set()
    
    for star_id, history in by_star.items():
        actions = [row.get("action_status") or "" for row in history[:5]]
        
        if any(a == "negative" for a in actions):
            penalties[star_id] = 1.0
            negative_set.add(star_id)
            continue
        
        if any(a in POSITIVE_FEEDBACK for a in actions):
            continue
        
        silent_count = len([a for a in actions if a in ("", "skipped")])
        penalty = max(0, silent_count * 0.15 - 0.15)
        # 1次→0, 2次→0.15, 3次→0.30, 4次→0.45, 5次→0.60
        if penalty > 0:
            penalties[star_id] = penalty
    
    return penalties, negative_set
```

恒星免疫在外层：`if row.get("is_constant"): features["ignored_penalty"] = 0.0`

---

## 三、候选过滤与排除

### 资格判定（RRF 之前）

一颗星被排除如果：
- `related_signal <= 0`（6 个通道原始分数全为零）
- `explicitly_negative = True`（最近 5 次反馈中有 `negative` 记录）

### related_signal

```python
related_signal = max(content_score, keyword_score, chord_score, harmony_score, scene_score, explicit_score)
```

---

## 四、`_select_for_chat_inject()` 选择逻辑

```python
def _select_for_chat_inject(self, scored, *, limit):
    min_score = self._min_score()           # 0.008
    related_min = self._related_min_score()  # 0.22
    
    # 第一轮：正常过阈值
    primary = [
        item for item in scored
        if item["final_score"] >= min_score
        and item["features"]["related_signal"] >= related_min
    ]
    
    # 第二轮：explicit fallback（仅在 primary 为空时）
    if not primary:
        primary = [
            item for item in scored
            if item["features"]["explicit_score"] > 0
        ][:STAR_CHAT_EXPLICIT_FALLBACK_LIMIT]  # 默认 1
    
    if not primary:
        return []
    
    # 第三轮：星座拉出
    remaining_slots = limit - len(primary)
    if remaining_slots > 0:
        primary_ids = {_node_id(item["row"]["id"]) for item in primary}
        pulled = self._constellation_pull(primary_ids, scored, exclude=primary_ids)
        combined = primary + pulled[:remaining_slots]
    else:
        combined = primary
    
    return combined[:limit]
```

### STAR_MIN_SCORE 阈值

v2: `0.18`（加权求和尺度）  
**v3: `0.008`**（RRF 尺度，环境变量 `STAR_MIN_SCORE`，范围 0.0–1.0）

### STAR_RELATED_MIN_SCORE

`0.22`（环境变量 `STAR_RELATED_MIN_SCORE`）— 至少有一个通道的原始分数 ≥ 0.22 才算"相关"。

---

## 五、星座拉出（Constellation Pull-Through）

**概念**：当一颗星因自身得分被选中注入时，沿 `constellation` 或 `harmony` 类型连线，把同星座兄弟拉进注入候选。

```python
async def _constellation_pull(self, anchor_ids, all_scored, exclude):
    # 查 star_links: relation_type in ('constellation','harmony'), 双向
    links = await self.supabase.query(...)
    
    linked_ids = {target_id for ... if target_id not in exclude}
    
    # 从已打分列表中取出
    pulled = [item for item in all_scored if _node_id(item["row"]["id"]) in linked_ids]
    
    # 过滤：negative 永远不拉，负分不拉
    pulled = [
        item for item in pulled
        if not item["features"].get("explicitly_negative")
        and item["final_score"] >= 0
    ]
    
    pulled.sort(key=lambda x: x["final_score"], reverse=True)
    return pulled
```

---

## 六、场景标签（Scene）

### 沈予的 6 个场景类型

| 底层 key | 沈予的名字 | 含义范围（仅为示例，不固定） |
|---|---|---|
| `warm` | 暖 | 情感、亲密、承诺、温度… |
| `deep` | 深 | 哲学、决定论、自由意志、存在… |
| `daily` | 日常 | 生活碎片、吃饭、天气、闲聊… |
| `rift` | 裂 | 冲突、认知变化、修复、和好… |
| `create` | 造 | 共建、房间、工具、创造… |
| `anchor` | 锚 | 仪式、立约、纪念日、标志性时刻… |

### 存储方式

`shenyu_stars.metadata` jsonb 字段（无需数据库迁移）：

```json
{
  "scene": "deep",
  "scene_tags": ["决定论", "自由意志"],
  "date_anchor": "2025-12-15"
}
```

### 查询时场景分类（两层）

**第一层：关键词规则**（快、准、零算力）

命中非 daily 的关键词 → 立即返回对应 scene。命中多个时取命中数最多的。

**第二层：embedding 兜底**（关键词未命中非 daily 场景时）

用 embedding 算 query 与 6 段场景描述的余弦相似度。≥ 0.45 取最高，< 0.45 回退 daily。

---

## 七、日期锚点（Date Anchor）

### 存储

`metadata.date_anchor`：`"YYYY-MM-DD"` 或 `"MM-DD"` 格式。

### 计算

```python
def _date_anchor_score(star_metadata, now) -> float:
    # 精确日期命中 → 1.0
    # 前后 1 天 → 0.75
    # 前后 2 天 → 0.50
    # 前后 3 天 → 0.25
    # >3 天 → 0.0
```

### v3 中的效果

日期锚点不再是加分项，而是 **乘性放大器** `date_mod = 1.0 + 0.3 × date_anchor_score`：
- 纪念日当天 → 该星所有通道贡献被放大 30%
- 这意味着：只有该星本身在某通道有排名时，日期才起作用——它不会让一颗完全无关的星浮出来

---

## 八、features dict 完整 schema (star-features-v3)

```python
features = {
    # --- 6 个通道原始分数 ---
    "content_score": float,         # max(content_overlap, vector_score)
    "keyword_score": float,         # token overlap ratio
    "chord_score": float,           # 和弦相似度 (0–0.85)
    "harmony_score": float,         # 星座连线传递
    "scene_score": float,           # 场景类型 + 标签匹配
    "explicit_score": float,        # min(1.0, significant_hits * 0.5)
    
    # --- 辅助特征 ---
    "date_anchor_score": float,     # 日期接近度 (0–1.0)
    "content_gravity_score": float, # max(content, keyword)
    "actr_score": float,            # ACT-R 认知激活原始值
    "constant_bonus": float,        # 1.0 if constant, else 0.0
    "novelty_bonus": float,         # 1.0 if never activated, else 0.0 (legacy)
    "ignored_penalty": float,       # 渐进 (0–0.6), 恒星免疫 (legacy)
    "recent_fatigue_penalty": float,
    "explicitly_negative": bool,
    "related_signal": float,        # max of 6 channels
    "explicit_mention": float,      # alias of explicit_score
    
    # --- RRF pass 后追加 ---
    "rrf_score": float,             # RRF 融合总分
    "rrf_contributions": dict,      # {channel_key: contribution}
    "actr_modifier": float,         # [0.5, 1.0]
    "novelty_modifier": float,      # 1/(1+log10(act+1))
    "constant_modifier": float,     # 1.3 or 1.0
    "fatigue_modifier": float,      # max(0, 1-penalty)
    "date_modifier": float,         # [1.0, 1.3]
}
```

---

## 九、配置项总览

```python
# StarWeights (RRF 通道权重)
star_rrf_ch_content: float = 1.0
star_rrf_ch_keyword: float = 0.8
star_rrf_ch_harmony: float = 0.7
star_rrf_ch_chord: float = 0.6
star_rrf_ch_explicit: float = 0.5
star_rrf_ch_scene: float = 0.4
star_rrf_k: int = 60

# 乘性修饰参数
star_rrf_actr_floor: float = 0.5
star_rrf_constant_boost: float = 1.3
star_rrf_date_boost_max: float = 0.3

# 阈值
star_min_score: float = 0.008
star_related_min_score: float = 0.22

# 疲劳
star_recent_fatigue_penalty: float = 0.14
star_recent_fatigue_hours: float = 6.0

# 场景
star_scene_rules_path: str = ""
star_scene_embedding_threshold: float = 0.45

# 版本
star_ranker_version: str = "star-ranker-v3"
```

所有参数支持环境变量动态调整。

---

## 十、场景规则配置文件

文件路径：`shenyu_gateway/star_scene_rules.json`

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

---

## 十一、回顾"降临arrive"案例（v3 视角）

```
query = "降临arrive...宇宙大爆炸宿命论决定论..."
star = 恒星"降临"（is_constant=true, activation_count=15, scene="anchor",
       scene_tags=["降临","决定论"], chord="Cm", date_anchor="12-15",
       今天不是 12-15）
```

**Step 1 — 6 通道原始分数**：

| 通道 | 原始分 | 在该通道的排名(假设) |
|------|--------|---------------------|
| content_score | 0.31 | #2 |
| keyword_score | 0.31 | #1 |
| scene_score | 0.70 | #1 |
| explicit_score | 1.00 | #1 |
| chord_score | 0.00 | (排除) |
| harmony_score | 0.00 | (排除) |

**Step 2 — RRF 融合（k=60）**：

```
rrf = 1.0/(60+2+1) + 0.8/(60+1+1) + 0.4/(60+1+1) + 0.5/(60+1+1)
    = 0.0159 + 0.0129 + 0.0065 + 0.0081
    ≈ 0.0434
```

**Step 3 — 乘性修饰**：

| 修饰因子 | 值 | 说明 |
|----------|-----|------|
| actr_mod | ~0.85 | 激活 15 次 → 有一定激活亮度 |
| novelty_mod | 0.45 | 1/(1+log10(16)) ≈ 0.45 |
| constant_mod | 1.30 | 恒星 ×1.3 |
| fatigue_mod | 1.00 | 未在近 6 小时注入 |
| date_mod | 1.00 | 今天不是 12-15 |

**最终**：

```
final = 0.0434 × 0.85 × 0.45 × 1.30 × 1.00 × 1.00
      ≈ 0.0216
```

**过阈值？** `0.0216 > 0.008`（STAR_MIN_SCORE）✓  
**related_signal？** `max(0.31, 0.31, 0.70, 1.00, 0, 0) = 1.00 > 0.22` ✓

恒星"降临"稳定入选。

---

## 十二、v2 → v3 对照表

| 维度 | v2 (旧) | v3 (当前) |
|------|---------|-----------|
| 评分模型 | 加权求和 (weighted sum) | RRF 融合 + 乘性修饰 |
| ranker version | `star-ranker-v2` | `star-ranker-v3` |
| feature schema | `star-features-v2` | `star-features-v3` |
| 权重含义 | 线性系数 (content=0.28...) | 通道重要性 (ch_content=1.0...) + RRF k=60 |
| constant 处理 | +0.08 加分 | ×1.3 乘数 |
| novelty | 新星 +0.04（二值） | 1/(1+log10(act+1)) 连续衰减 |
| ignored_penalty | 渐进罚分（线性扣） | 不参与评分，改用 novelty_mod 自然覆盖 |
| date_anchor | 加分 (+0.12) | 乘性 1 + 0.3 × date_score |
| fatigue | 直接扣 recent_fatigue_penalty | ×max(0, 1-penalty) 乘性 |
| 公式 | sum(feature×weight) - penalties | rrf × actr × novelty × constant × fatigue × date |
| STAR_MIN_SCORE | 0.18 | 0.008 |

---

## 十三、数据库变更

### 不需要 schema migration

所有新字段使用已有的 `metadata jsonb`，与 v2 一致。

---

## 十四、版本管理

- `STAR_RANKER_VERSION`: `"star-ranker-v3"`
- `STAR_FEATURE_SCHEMA_VERSION`: `"star-features-v3"`
- `STAR_WEIGHTS_VERSION`: `"rrf-v1"`
- 回退：暂不支持回退至 v2（加权求和代码已移除）

---

*— 圆儿 & Codex, 2026.06.27 (基于 e79440c 实际代码重写)*
