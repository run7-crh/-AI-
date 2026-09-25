# 导入 MarkdownReader 基类，在其基础上扩展 Obsidian 专用处理
from llama_index.readers.file import MarkdownReader
# 导入 LlamaIndex 文档数据结构
from llama_index.core.schema import Document
# 导入正则模块，用于剥离 wikilink/callout/embed 语法
import re
# 导入 frontmatter 库，用于解析 .md 开头的 YAML 元数据
import frontmatter
# 导入 Path，用于处理文件路径
from pathlib import Path
# 导入 sha256，用于生成稳定的文档 id
from hashlib import sha256


# 定义 Obsidian 专用 Markdown 读取器，继承自 MarkdownReader
class ObsidianMarkdownReader(MarkdownReader):
    """Obsidian .md 文件读取器，处理 wikilink/callout/embed/frontmatter。"""

    # 覆写加载数据方法：文件路径 → 一个 Document
    def load_data(self, file_path, extra_info=None, fs=None):
        file_path = Path(file_path)        # 转换为 Path 对象
        post = frontmatter.load(file_path) # 解析 frontmatter（YAML）+ 正文
        content = post.content             # 取正文文本
        metadata = dict(post.metadata)     # 取元数据（YAML 部分）转 dict

        content = self._strip_wikilinks(content)  # 剥离 [[wikilink]] 语法
        content = self._strip_callouts(content)   # 剥离开头 callout 语法
        content = self._strip_embeds(content)     # 剥离 ![[embed]] 语法

        # Chroma 向量存储要求 metadata 值为 str/int/float/None，
        # tags 在 Obsidian frontmatter 中通常是 list，需展平为字符串。
        tags = metadata.get("tags", [])    # 取 tags 字段
        if isinstance(tags, list):         # 若是列表
            tags = ",".join(str(t) for t in tags)  # 用逗号拼接为字符串
        elif not isinstance(tags, (str, int, float, type(None))):  # 若是其他复杂类型
            tags = str(tags)               # 转字符串

        extra_info = extra_info or {}      # 初始化额外元数据
        # Keep a stable document identifier across rebuilds.  The vector
        # collection is cleared before each rebuild, but this identifier is
        # still useful when tracing and comparing evidence over time.
        document_id = sha256(              # 用文件名+正文生成稳定哈希 id
            f"{file_path.name}\x00{content}".encode("utf-8")
        ).hexdigest()
        extra_info.update({                # 合并元数据
            "file_name": file_path.name,         # 文件名
            "title": str(metadata.get("title") or file_path.stem),  # 标题（无则用文件名）
            "tags": tags,                        # 展平后的标签
            "source": str(file_path),            # 来源路径
            "source_type": "local",              # 来源类型=本地
            "document_id": document_id,          # 稳定文档 id
        })

        return [Document(text=content, metadata=extra_info, id_=document_id)]  # 返回文档单元素列表

    # 定义 wikilink 剥离方法
    def _strip_wikilinks(self, text: str) -> str:
        # 注意：group(1) 必须排除 '|'，否则 [[A|B]] 中 group(1) 会贪婪吞掉 "A|B"
        return re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]',  # 匹配 [[A]] 或 [[A|B]]
                      lambda m: m.group(2) or m.group(1), text)  # 有别名取别名，否则取原名

    # 定义 callout 剥离方法
    def _strip_callouts(self, text: str) -> str:
        return re.sub(r'^>\s*\[!\w+\]\s*', '> ', text, flags=re.MULTILINE)  # 模板化 callout 记号变为普通引用

    # 定义 embed 剥离方法
    def _strip_embeds(self, text: str) -> str:
        return re.sub(r'!\[\[[^\]]+\]\]', '', text)  # 删掉 ![[...]] 嵌入语法


# drone 知识库中不参与向量索引的辅助文件（相对 data/drone 的 POSIX 路径）
# README 是知识库规范说明、sources/sources.md 是来源登记表，入库会污染检索召回
DRONE_KB_EXCLUDED_FILES = frozenset({"README.md", "sources/sources.md"})


# 定义知识库 Markdown 遍历函数（indexer 与 graph_builder 共用）
def iter_kb_markdown_files(data_dir: Path, recursive: bool = False) -> list[Path]:
    """按知识库类型遍历 Markdown 文件：

    - recursive=False（obsidian 顶层库）：仅遍历顶层 *.md，保持既有行为不变
    - recursive=True（drone 子目录库）：rglob 递归遍历，并排除 README/sources 登记文件
    """
    data_dir = Path(data_dir)          # 统一转 Path
    if not recursive:                  # 顶层库：原行为
        return sorted(data_dir.glob("*.md"))
    files: list[Path] = []             # 递归库：收集非排除文件
    for path in sorted(data_dir.rglob("*.md")):
        if path.relative_to(data_dir).as_posix() in DRONE_KB_EXCLUDED_FILES:  # 命中排除清单
            continue                   # 跳过
        files.append(path)             # 保留
    return files


# 定义 Chroma 标量值展平函数：metadata 值只接受 str/int/float/bool/None
def _flatten_chroma_value(value):
    if isinstance(value, (list, tuple)):           # 列表（如 source_id）→ 逗号拼接
        return ",".join(str(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):  # 已是合法标量
        return value
    return str(value)                              # 其余复杂类型转字符串


# 定义 drone 售后知识库读取器：在 Obsidian 处理之上提升 frontmatter 身份字段
class DroneMarkdownReader(ObsidianMarkdownReader):
    """data/drone 读取器：把 frontmatter 的售后身份字段提升为向量 metadata。

    这些字段（机型/部件/故障类型/数据性质/来源）随 Evidence 透出，供按机型
    匹配与安全处置引用。Chroma 不接受列表值，source_id 等列表字段展平为
    逗号分隔字符串。
    """

    # 需要提升为 metadata 的身份字段（document_id 单独处理，见 load_data）
    DRONE_METADATA_FIELDS = (
        "document_type", "product_model", "component", "fault_type",
        "data_type", "source_type", "source_id", "version",
    )

    # 覆写加载数据方法：先走基类完整解析，再叠加 drone 身份字段
    def load_data(self, file_path, extra_info=None, fs=None):
        documents = super().load_data(file_path, extra_info=extra_info, fs=fs)
        # 基类内部已解析过 frontmatter；这里再读一次以取身份字段。
        # 文件均为本地小 md，二次解析成本可忽略，换取基类（obsidian 路径）零改动。
        drone_meta = frontmatter.load(file_path).metadata  # 取 frontmatter 原始元数据
        for document in documents:                 # 遍历（当前实现为单文档）
            # frontmatter 的 document_id 是知识库身份标识，覆盖基类的哈希 id；
            # Document.id_ 需同步：LlamaIndex 落库时 chroma metadata 的 document_id
            # 取 ref_doc_id（即 Document.id_），不同步则检索证据透出的是哈希。
            # 同步后 chunk id 形如 "<document_id>:chunk:0"，重建依然稳定。
            # frontmatter 缺失 document_id 时保持基类哈希回退。
            kb_document_id = str(drone_meta.get("document_id") or "").strip()
            if kb_document_id:
                document.metadata["document_id"] = kb_document_id
                document.id_ = kb_document_id
            for field in self.DRONE_METADATA_FIELDS:  # 逐字段提升
                value = _flatten_chroma_value(drone_meta.get(field))  # 展平为标量
                if value is None or value == "":       # 空值不写入
                    continue
                document.metadata[field] = value
            # drone 文档无 title frontmatter，基类回退为文件名 stem；
            # 这里提升正文第一个一级标题作为展示标题（来源卡片与引用更可读）。
            title = str(document.metadata.get("title") or "")
            if not title or title == Path(file_path).stem:
                h1 = re.search(r"^#\s+(.+)$", document.text, re.MULTILINE)  # 找首个 H1
                if h1:                                 # 有 H1 才覆盖
                    document.metadata["title"] = h1.group(1).strip()
        return documents                           # 返回文档列表