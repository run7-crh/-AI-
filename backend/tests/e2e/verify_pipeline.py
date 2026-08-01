# backend/tests/e2e/verify_pipeline.py
"""端到端验证脚本：embedding → DeepSeek LLM → 索引重建 → RAG 检索 → LangGraph 工作流。

使用方法（在 backend 目录下）:
    python -m tests.e2e.verify_pipeline
或:
    python tests/e2e/verify_pipeline.py

不修改任何源代码，仅做只读验证。索引会写入 CHROMA_PERSIST_DIR。
"""
import asyncio
import logging
import sys
import time
from pathlib import Path

# 确保 backend 在 sys.path
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("e2e_verify")


def step(num: int, title: str):
    logger.info("=" * 60)
    logger.info(f"STEP {num}: {title}")
    logger.info("=" * 60)


async def main():
    from app.config import settings

    # ----------------------------------------------------------------
    step(1, "验证 embedding 模型加载（本地 HuggingFace BGE）")
    # ----------------------------------------------------------------
    t0 = time.time()
    # P2-2: 显式调用 configure_embedding()，不再依赖模块导入副作用
    from app.rag.embedding import configure_embedding
    configure_embedding()
    from llama_index.core import Settings
    embed_model = Settings.embed_model
    if embed_model is None:
        logger.error("FAIL: Settings.embed_model 为 None")
        sys.exit(1)
    test_text = "什么是 RAG 检索增强生成"
    vec = embed_model.get_text_embedding(test_text)
    logger.info(f"OK: embedding 加载完成, 维度={len(vec)}, 耗时={time.time()-t0:.2f}s")
    logger.info(f"  向量前5维: {vec[:5]}")

    # ----------------------------------------------------------------
    step(2, "验证 DeepSeek LLM 调用")
    # ----------------------------------------------------------------
    from app.graph.tools import call_llm
    t0 = time.time()
    try:
        result = await call_llm(
            system_prompt="你是一个测试助手，请用一句话回答。",
            user_input="用一句话解释什么是 Agent。",
            temperature=0.3,
            model=settings.MODEL_PRO_CHAT,
        )
        logger.info(f"OK: deepseek-chat 调用成功, 耗时={time.time()-t0:.2f}s")
        logger.info(f"  响应: {result['text'][:200]}")
    except Exception as e:
        logger.error(f"FAIL: deepseek-chat 调用失败: {type(e).__name__}: {e}")
        sys.exit(1)

    # 测试 deepseek-reasoner
    t0 = time.time()
    try:
        result = await call_llm(
            system_prompt="你是一个推理助手。",
            user_input="9.11 和 9.9 哪个大？只回答数字。",
            temperature=0.3,
            model=settings.MODEL_PRO_REASON,
        )
        logger.info(f"OK: deepseek-reasoner 调用成功, 耗时={time.time()-t0:.2f}s")
        logger.info(f"  响应: {result['text'][:200]}")
    except Exception as e:
        logger.warning(f"WARN: deepseek-reasoner 调用失败: {type(e).__name__}: {e}")

    # ----------------------------------------------------------------
    step(3, "重建 Chroma 索引（用本地 BGE embedding 处理 Obsidian 知识库）")
    # ----------------------------------------------------------------
    from app.rag.indexer import Indexer
    data_dir = Path(settings.KB_DATA_DIR)
    if not data_dir.exists():
        logger.error(f"FAIL: 知识库目录不存在: {data_dir}")
        sys.exit(1)
    md_files = list(data_dir.glob("*.md"))
    logger.info(f"知识库目录: {data_dir}")
    logger.info(f"找到 {len(md_files)} 个 .md 文件")

    t0 = time.time()
    indexer = Indexer(
        data_dir=str(data_dir),
        persist_dir=settings.CHROMA_PERSIST_DIR,
    )
    # 强制重建（不用 load_or_build）
    indexer.build()
    logger.info(f"OK: 索引重建完成, 耗时={time.time()-t0:.2f}s")

    # 检查 Chroma collection 内文档数
    try:
        count = indexer.chroma_collection.count()
        logger.info(f"  Chroma collection 文档数: {count}")
    except Exception as e:
        logger.warning(f"  无法获取 collection count: {e}")

    # ----------------------------------------------------------------
    step(4, "验证 RAG 检索功能")
    # ----------------------------------------------------------------
    retriever = indexer.get_retriever()
    test_queries = [
        "什么是 RAG？",
        "LangGraph 和 LangChain 有什么区别？",
        "什么是模型幻觉？",
    ]
    for q in test_queries:
        t0 = time.time()
        results = await asyncio.to_thread(retriever.retrieve, q)
        logger.info(f"Q: {q}  (耗时 {time.time()-t0:.2f}s, 命中 {len(results)} 条)")
        for i, r in enumerate(results):
            content_preview = r["content"][:80].replace("\n", " ")
            logger.info(f"  [{i+1}] score={r['score']:.4f}  source={r['source']}")
            logger.info(f"      {content_preview}...")

    # ----------------------------------------------------------------
    step(5, "跑完整 LangGraph 工作流端到端测试")
    # ----------------------------------------------------------------
    from app.graph.builder import build_graph
    graph = build_graph(retriever)

    test_cases = [
        {
            "query": "什么是 RAG 检索增强生成？它解决了什么问题？",
            "desc": "本地知识库相关查询（应走 RAG 路径）",
        },
        {
            "query": "2024 年诺贝尔物理学奖得主是谁？",
            "desc": "本地知识库无关查询（应走 web_search 路径）",
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        logger.info(f"--- 测试用例 {i}: {tc['desc']} ---")
        logger.info(f"Query: {tc['query']}")
        initial_state = {
            "query": tc["query"],
            "conversation_id": f"e2e-test-{i}",
            "history": [],
        }
        t0 = time.time()
        try:
            # 设置 recursion_limit 避免无限循环
            final_state = await graph.ainvoke(
                initial_state,
                config={"recursion_limit": 25},
            )
            elapsed = time.time() - t0
            logger.info(f"OK: 工作流执行完成, 耗时={elapsed:.2f}s")
            logger.info(f"  route_path: {final_state.get('route_path')}")
            logger.info(f"  is_relevant: {final_state.get('is_relevant')}")
            logger.info(f"  rag_quality_pass: {final_state.get('rag_quality_pass')}")
            logger.info(f"  answer_quality_pass: {final_state.get('answer_quality_pass')}")
            logger.info(f"  has_hallucination: {final_state.get('has_hallucination')}")
            final_answer = final_state.get("final_answer", "")
            logger.info(f"  final_answer (前300字): {final_answer[:300]}")
            judge_log = final_state.get("judge_log", [])
            logger.info(f"  judge_log 条数: {len(judge_log)}")
            for j, jl in enumerate(judge_log):
                logger.info(f"    [{j+1}] {jl.get('judge_type')}: passed={jl.get('passed')}")
        except Exception as e:
            logger.error(f"FAIL: 工作流执行失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    logger.info("=" * 60)
    logger.info("端到端验证完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
