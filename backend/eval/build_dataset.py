"""把 data/raw/test_questions.json 转换成 eval/dataset.json 格式。

用法：
    cd backend
    python eval/build_dataset.py
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

SOURCE = ROOT_DIR / "data" / "raw" / "test_questions.json"
TARGET = BACKEND_DIR / "eval" / "dataset.json"

CATEGORY_MAP = {
    "knowledge_hit": "knowledge_hit",
    "knowledge_miss": "knowledge_missing",
    "multi_hop": "multi_hop",
    "hallucination_prone": "hallucination_test",
    "fuzzy": "routing_test",
}

# 主题 → 预期来源文件名（从 data/raw 下的 .md 文件名匹配）
SOURCE_MAP = {
    "rag": "RAG 检索增强生成.md",
    "检索增强生成": "RAG 检索增强生成.md",
    "agent": "Agent.md",
    "智能体": "Agent.md",
    "agent智能体": "Agent智能体.md",
    "workflow": "Agent与Workflow的区别.md",
    "agent与workflow": "Agent与Workflow的区别.md",
    "记忆": "Agent记忆机制.md",
    "agent记忆": "Agent记忆机制.md",
    "embedding": "Embedding 向量嵌入.md",
    "向量嵌入": "Embedding 向量嵌入.md",
    "function calling": "Function Calling 函数调用.md",
    "tool calling": "Tool Calling 工具调用.md",
    "harness engineering": "Harness Engineering 驾驭工程.md",
    "驾驭工程": "Harness Engineering 驾驭工程.md",
    "llm": "LLM 大语言模型.md",
    "大语言模型": "LLM 大语言模型.md",
    "langchain": "LangChain-LangGraph.md",
    "langgraph": "LangChain-LangGraph.md",
    "loop engineering": "Loop Engineering 循环工程.md",
    "循环工程": "Loop Engineering 循环工程.md",
    "mcp": "MCP 模型上下文协议.md",
    "模型上下文协议": "MCP 模型上下文协议.md",
    "prompt": "Prompt Engineering 提示词工程.md",
    "提示词工程": "Prompt Engineering 提示词工程.md",
    "react": "ReAct 推理框架.md",
    "transformer": "Transformer.md",
    "向量数据库": "向量数据库.md",
    "微调": "微调.md",
    "lora": "微调.md",
    "qlora": "微调.md",
    "sft": "微调.md",
    "rlhf": "微调.md",
    "dpo": "微调.md",
    "幻觉": "模型幻觉.md",
}


def normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text).lower()


def infer_expected_source(question: str, notes: str) -> str | None:
    """根据问题中的关键词推断 expected_source，未命中返回 None。"""
    combined = normalize(question + " " + notes)
    # 优先匹配更具体的复合主题
    ordered_keys = sorted(SOURCE_MAP.keys(), key=lambda k: -len(k))
    for key in ordered_keys:
        if normalize(key) in combined:
            return SOURCE_MAP[key]
    return None


def generate_keywords(question: str, notes: str, category: str) -> list[str]:
    """基于问题生成简单的预期答案关键词。

    策略：
    - 优先保留英文/数字技术术语（RAG、Agent、LoRA、MCP 等），这些最稳定；
    - 中文按字拆分后提取 2-3 字连续片段，过滤单字停用词；
    - hallucination_test / knowledge_missing / routing_test 返回空列表。
    """
    if category in ("hallucination_test", "knowledge_missing", "routing_test"):
        return []

    text = question
    # 单字停用词
    char_stops = set(
        "是什么的了吗呢啊和跟与有在了吧之用作为它我你这个那个那种这些那些就是"
        "没有能不能行不行可以需要应该会被把让给对将从到上下中里前后主要解决"
        "问题区别差异联系关系关联核心本质基本基础概念定义流程步骤机制方式方法"
        "技术原理思想作用功能模块负责分别各自适合场景哪些为个种还于而"
    )

    keywords = []
    seen = set()

    # 1) 英文/数字术语
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-\.]*(?:\s+[a-zA-Z][a-zA-Z0-9\-\.]*)*", text):
        token = w.strip().lower().replace(" ", " ")
        # 过滤纯数字、过短、常见停用英文词
        if re.fullmatch(r"\d+", token) or len(token) < 2 or token in {"is", "it", "the", "a", "an"}:
            continue
        if token not in seen:
            seen.add(token)
            keywords.append(w.strip())

    # 2) 中文 bigram / trigram
    chars = [c for c in text if "\u4e00" <= c <= "\u9fa5"]
    for n in (3, 2):
        for i in range(len(chars) - n + 1):
            gram = "".join(chars[i : i + n])
            # 只要片段中不含停用字且不在句首疑问位置，就认为可能是术语
            if any(c in char_stops for c in gram):
                continue
            if gram not in seen:
                seen.add(gram)
                keywords.append(gram)

    # 3) 若前面提取太少，补一些未过滤的中文词（兜底）
    if len(keywords) < 2:
        for w in re.findall(r"[\u4e00-\u9fa5]{2,}", text):
            if any(c in char_stops for c in w):
                continue
            if w not in seen and len(w) <= 6:
                seen.add(w)
                keywords.append(w)

    return keywords[:6]


def main():
    with open(SOURCE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    questions = []
    cat_counts = {}
    for i, q in enumerate(raw, 1):
        cat = CATEGORY_MAP.get(q["category"], q["category"])
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        notes = q.get("notes", "")
        expected_source = infer_expected_source(q["question"], notes)
        keywords = generate_keywords(q["question"], notes, cat)
        questions.append(
            {
                "id": f"q{i:03d}",
                "question": q["question"],
                "acceptable_routes": [q["expected_route"]],
                "expected_answer_keywords": keywords,
                "expected_source": expected_source,
                "difficulty": q["difficulty"],
                "category": cat,
                "source_type": "seed",
            }
        )

    dataset = {
        "version": "1.1",
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_distribution": {"seed": len(questions), "ai_expanded": 0, "from_query_log": 0},
        "questions": questions,
    }

    # 备份旧 dataset.json
    if TARGET.exists():
        backup = TARGET.with_name("dataset_seed_v1.0.json")
        if not backup.exists():
            TARGET.rename(backup)
            print(f"已备份原 dataset.json -> {backup.name}")

    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"已生成 {TARGET}，共 {len(questions)} 题")
    print("类别分布:", cat_counts)


if __name__ == "__main__":
    main()
