"""追踪 4 轮对话的节点路径 + 幻觉检测。"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def create_conversation() -> str:
    req = urllib.request.Request(
        f"{BASE}/api/conversations",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"title": "路由追踪+幻觉测试"}).encode(),
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["id"]


def chat(conv_id: str, message: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/chat",
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        data=json.dumps({"conversation_id": conv_id, "message": message}).encode(),
    )
    stages = []
    tokens = []
    meta = None
    error = None
    done = False

    with urllib.request.urlopen(req, timeout=180) as r:
        buffer = ""
        for chunk in iter(lambda: r.read(1024), b""):
            buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
            while "\n\n" in buffer:
                raw = buffer.split("\n\n", 1)[0]
                buffer = buffer.split("\n\n", 1)[1]
                data_str = ""
                for line in raw.split("\n"):
                    if line.startswith("data:"):
                        data_str += line[5:].strip()
                if not data_str:
                    continue
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                t = evt.get("type")
                if t == "stage":
                    stages.append(evt["data"])
                elif t == "token":
                    tokens.append(evt["data"])
                elif t == "meta":
                    meta = evt["data"]
                elif t == "error":
                    error = evt["data"]
                elif t == "done":
                    done = True

    return {
        "stages": stages,
        "answer": "".join(tokens),
        "meta": meta,
        "error": error,
        "done": done,
    }


def analyze_hallucination(label: str, query: str, result: dict) -> list:
    """启发式幻觉检测。返回发现的问题列表。"""
    issues = []
    answer = result["answer"]
    meta = result.get("meta") or {}

    # 1. 答案是否为空或过短
    if len(answer.strip()) < 20:
        issues.append(f"答案过短({len(answer.strip())}字): {answer!r}")

    # 2. 答案开头是否重复 query（生成异常信号）
    # 例如 "RAG和微调的区别RAG和微调是..."
    if answer and query and answer.startswith(query[:5]):
        # 允许部分重叠，但若答案前 20 字几乎等于 query，可能是异常
        prefix = answer[:len(query)+5]
        if query in prefix:
            issues.append(f"答案开头疑似重复 query: {prefix!r}")

    # 3. 是否包含引用来源标注
    has_source = "[来源：" in answer or "[来源:" in answer
    route = meta.get("route_path", "")
    if route in ("local", "online", "decomposition"):
        if not has_source:
            issues.append(f"路径={route} 但答案无 [来源：] 标注")

    # 4. combined_quality 是否通过
    jl = meta.get("judge_log") or []
    combined = next((j for j in jl if j.get("judge_type") == "combined_quality"), None)
    if combined and not combined.get("passed"):
        issues.append(f"combined_quality 未通过: {combined.get('reason')}")
        if meta.get("quality_warning"):
            issues.append(f"quality_warning: {meta.get('quality_warning')}")

    # 5. 是否出现明显的模板失败文本
    if "抱歉，我暂时无法给出高质量的回答" in answer:
        issues.append("返回了质量失败兜底文本")

    # 6. 答案是否包含"我不知道"类无内容回答
    low_info_markers = ["我不知道", "无法回答", "没有相关信息", "知识库中没有"]
    if any(m in answer for m in low_info_markers) and route == "local":
        issues.append(f"local 路径返回低信息回答")

    return issues


def main():
    print("=" * 70)
    print("创建会话...")
    conv_id = create_conversation()
    print(f"会话 ID: {conv_id}\n")

    queries = [
        ("第一轮", "什么是RAG"),
        ("第二轮", "介绍一下江门"),
        ("第三轮", "LangChain,LangGraph和LlamaIndex的区别"),
        ("第四轮", "RAG和微调的区别"),
    ]

    results = []
    for label, q in queries:
        print("=" * 70)
        print(f"{label} 提问：{q}")
        print("-" * 70)
        t0 = time.time()
        r = chat(conv_id, q)
        elapsed = time.time() - t0
        print(f"耗时: {elapsed:.1f}s")
        print(f"节点阶段序列（{len(r['stages'])}个）:")
        for i, s in enumerate(r["stages"], 1):
            print(f"  {i:2d}. {s}")
        print(f"\n完整答案 ({len(r['answer'])}字):")
        print(r["answer"])
        if r["meta"]:
            print(f"\nmeta.route_path: {r['meta'].get('route_path')}")
            print(f"meta.quality_warning: {r['meta'].get('quality_warning')}")
            jl = r["meta"].get("judge_log") or []
            print(f"meta.judge_log ({len(jl)}条):")
            for j in jl:
                print(f"  - {j.get('judge_type')} passed={j.get('passed')} reason={j.get('reason')}")
        if r["error"]:
            print(f"ERROR: {r['error']}")

        # 幻觉检测
        issues = analyze_hallucination(label, q, r)
        print(f"\n幻觉/质量启发式检查 ({len(issues)}项):")
        if issues:
            for iss in issues:
                print(f"  ⚠️ {iss}")
        else:
            print("  ✅ 未发现明显异常")
        print()
        results.append((label, q, r, issues))

    # 汇总
    print("=" * 70)
    print("节点路径汇总：")
    print("=" * 70)
    for label, q, r, issues in results:
        route = (r.get("meta") or {}).get("route_path", "?")
        print(f"\n{label}: {q}")
        print(f"  route_path: {route}")
        print(f"  阶段序列: {' -> '.join(r['stages'])}")
        print(f"  问题数: {len(issues)}")
        if issues:
            for iss in issues:
                print(f"    - {iss}")


if __name__ == "__main__":
    main()
