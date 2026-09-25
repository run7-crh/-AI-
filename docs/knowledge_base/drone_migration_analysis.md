---
title: 无人机售后支持知识库迁移分析
document_type: migration_analysis
related_project: 无人机智能售后技术支持 Agent
version: "1.0"
language: zh-CN
created_at: 2026-09-18
updated_at: 2026-09-18
---

# 无人机售后支持知识库 — 迁移分析

> 本文档对当前项目已有知识库资产（`data/raw`、`data/processed`）进行**只读分析**，
> 说明现有数据流、raw/processed 的关系，以及「无人机售后知识库」为何必须独立于现有数据新建、
> 而不应覆盖现有数据。

---

## 1. 分析范围与合规声明

本次分析**未修改任何文件**，仅通过 `Read` / `Get-ChildItem` / `Select-String` 进行读取与对比。
涉及禁止事项逐项确认：

- 未删除 / 移动 / 覆盖 `data/raw/*` 中任何文件。
- 未删除 / 移动 / 覆盖 `data/processed/*` 中任何文件。
- 未修改 `backend/app/rag/readers.py`、`indexer.py`、`retriever.py`、`embedding.py`。
- 未修改 Chroma 索引、评测数据、LangGraph / FastAPI / 前端代码。

## 2. 现状盘点

### 2.1 `data/raw/`（20 个 .md + 1 个 .json）

| 文件 | 大小 | 状态 |
|------|------|------|
| `Agent.md` | 15,736 B | 正常 |
| `Agent与Workflow的区别.md` | 35,289 B | 正常 |
| `Agent智能体.md` | 37 B | ⚠️ **破损**（仅有 frontmatter，正文为空） |
| `Agent记忆机制.md` | 31,027 B | 正常 |
| `Embedding 向量嵌入.md` | 25,297 B | 正常 |
| `Function Calling 函数调用.md` | 34,041 B | 正常 |
| `Harness Engineering 驾驭工程.md` | 33,437 B | 正常 |
| `LangChain-LangGraph.md` | 26,997 B | 正常 |
| `LLM 大语言模型.md` | 28,950 B | 正常 |
| `Loop Engineering 循环工程.md` | 34,867 B | 正常 |
| `MCP 模型上下文协议.md` | 28,856 B | 正常 |
| `Prompt Engineering 提示词工程.md` | 22,358 B | 正常 |
| `RAG 检索增强生成.md` | 21,349 B | 正常（带空格标题） |
| `RAG检索增强生成.md` | 1,883 B | ⚠️ **残留重复**（无空格标题，内容较完整版本短很多） |
| `ReAct 推理框架.md` | 34,610 B | 正常 |
| `Tool Calling 工具调用.md` | 29,006 B | 正常 |
| `Transformer.md` | 21,649 B | 正常 |
| `向量数据库.md` | 23,666 B | 正常 |
| `微调.md` | 33,527 B | 正常 |
| `模型幻觉.md` | 23,824 B | 正常 |
| `test_questions.json` | 26,873 B | 评测用测试题（非知识正文） |

### 2.2 `data/processed/`（18 个 .md）

包含与 raw **同名的 18 个主题文件**（`Agent.md` … `模型幻觉.md`），
**不包含** raw 中的两个异常文件（`Agent智能体.md`、`RAG检索增强生成.md`），
也不包含 `test_questions.json`。

即 processed = raw 剔除「破损文件 + 重复残留 + 评测数据」后的**清洗版本**。

## 3. 数据流分析（代码级证据）

### 3.1 入口配置

`backend/app/config.py:27`

```
KB_DATA_DIR: str = str(_PROJECT_ROOT / "data" / "raw")
```

### 3.2 谁在读取 `data/raw`

- **`indexer.py`（`build()`，第 183 行）**
  `for md_file in sorted(self.data_dir.glob("*.md"))`
  - 只遍历 `data_dir` **顶层**的 `*.md`（不递归子目录）。
  - 用 `frontmatter` 解析 YAML 头；正文小于 `MIN_BODY_CHARS=200` 的文档被跳过（第 190 行）。
  - 按归一化标题 `re.sub(r"\s+","",title).casefold()` 去重，标题重复时保留**正文更长**的版本。
- **`graph_builder.py:343`** `raw_dir = Path(settings.KB_DATA_DIR)` — 全量重建知识图谱时读 raw。

### 3.3 谁在读取 `data/processed`

代码中**没有任何引用**（`Select-String 'processed'` 在 `backend/app`、`backend/eval` 下零命中）。
`data/processed` 当前是**未被运行时管线消费**的离线 / 人工清洗目录。

### 3.4 Chroma 索引与数据目录对应关系

- 持久化目录：`backend/data/chroma/`（`.gitignore` 已忽略）。
- collection：`obsidian_kb`（可配置 `CHROMA_COLLECTION_NAME`）。
- 活动集合通过 `obsidian_kb.active.json` 指针切换（版本化 `obsidian_kb__v_<uuid>`）。
- 构建流程：`data/raw/*.md` → `ObsidianMarkdownReader`（剥离 wikilink/callout/embed、解析 frontmatter、按
  `文件名\x00正文` 生成稳定 `document_id`）→ `SentenceSplitter(chunk=512, overlap=50)` → BGE Embedding → Chroma。

### 3.5 当前知识库实际数据流（示意）

```
data/raw/*.md (源)
   │  Indexer.build(): glob("*.md") 顶层、frontmatter、去重(保留更长)
   ▼
Page:  文档 → 分块(SentenceSplitter 512/50) → BGE 向量化
   ▼
Chroma: obsidian_kb__v_<uuid>（backend/data/chroma，.gitignore 忽略）
   │  load_or_build() 空索引/策略变化/旧版迁移时自动 rebuild
   ▼
Retriever(top_k=3) + Reranker(bge-reranker-v2-m3) → RAG 生成

data/processed/*.md (清洗版，当前未被任何代码消费)
```

## 4. raw / processed 的「源-处理」关系判断

**结论：`data/processed` 在语义上是 `data/raw` 的清洗去重结果，但在运行时没有被接线（not wired-in）。**

- 文件命名高度对应（18 个同名 .md）。
- processed 恰好剔除了 raw 中的两个异常文件（破损的 `Agent智能体.md`、内容重复且更短的 `RAG检索增强生成.md`），这符合「清洗 / 去重 / 标准化」的目标。
- 但 `config.KB_DATA_DIR` 指向 `raw`，`indexer` 与 `graph_builder` 都读 `raw`；
  **`processed` 目前只是人工维护的干净副本，并不参与构建。**

隐含风险（供后续阶段关注，本次不改）：
- indexer 读 raw 意味着 `RAG检索增强生成.md`（1,883 B 重复主题）也会被建入索引，可能造成主题重复召回。
- `Agent智能体.md` 因正文 < 200 字符被 indexer 静默跳过，符合既有设计，但易被误认为「丢了内容」。

## 5. 为什么「无人机售后知识库」不应覆盖现有数据

1. **主题域完全不同。** 现有 raw/processed 是「AI / 编程学习」，无人机售后是「产品 / 故障 / SOP / 安全 / 售后案例」。
   若写入同一目录被现有 indexer 建入同一 collection，会互相污染检索召回，破坏现有 AI 知识库的精度。
2. **数据性质不同。** 无人机数据强调「可追溯、逐型号、逐来源、事实性」，而现有 AI 内容更偏「概念综述」。
   元数据 schema（`product_model / component / fault_type / source_id / data_type`）与现有 frontmatter（`title / tags`）字段不兼容。
3. **数据可信度纪律不同。** 无人机知识严格禁止编造，且需要专门的 `sources.md` 溯源登记，
   与现有知识的生产方式不同，也不该混在同一目录里由同一批文件承担。
4. **版权与隐私风险不同。** 无人机资料涉及厂商文档版权与监管（民用无人驾驶航空器），
   需要独立目录独立管理（例如只存 URL/元数据而非整本 PDF）。
5. **后续 RAG 接入需要干净边界。** 下一阶段若要接入，最稳妥的方式是给无人机库**独立的
   `data_dir` 与独立 Chroma collection**，在现有管线不动的前提下增量追加，而不是覆写已有 20 个文件。

## 6. 新知识库建议目录

按需求建议，在根目录 `data/` 下**新增该目录（唯一新增目录）**：

```
data/drone/
├── sources/          # 来源登记（sources.md + 可选本地副本）
├── products/         # 产品定位/型号/规格/组成/控制/载荷/传感器/通信/飞行
├── technical/        # 飞控/GNSS/IMU/罗盘/电机/桨/电池/遥控/图传/通信/固件/校准/飞行模式
├── troubleshooting/  # 故障现象/原因/排查/升级条件
├── sop/              # 标准操作流程
├── safety/           # 飞行/电池/安全检查/环境限制/维护安全
├── cases/            # synthetic 模拟售后案例
├── manifest.json     # 文档登记（document_id / file_path / type / model / source / data_type）
└── README.md         # 知识库说明与使用规范
```

**目录取舍的理由：**
- `products/`、`technical/`、`troubleshooting/`、`sop/`、`safety/`、`cases/`、`sources/` 均保留——
  与「产品查询 / 技术查询 / 故障分析 / SOP 推荐 / 案例检索 / 溯源」业务目标一一对应。
- `safety/` 虽与部分 SOP 有交集，但安全内容需独立承载监管要求与高风险操作纪律，独立成目录更利于检索与审核。
- 未新增其他目录：当前 6 类已能与既有原始清单（产品/技术/故障/流程/安全/案例）对齐，
  后续若需「故障码词典」或「法规手册」，可在接入阶段再增量增加，届时更新本报告。

## 7. 本次任务边界重申

- 只读分析旧数据，**不删除 / 不移动 / 不覆盖 / 不修改** 任何现有知识库文件。
- 不改 `backend/`、`frontend/`、LangGraph、RAG、Retriever、Indexer、Reader、Chroma、FastAPI、评测数据。
- 新增内容全部落在 `data/drone/` 与 `docs/knowledge_base/` 内。