from llama_index.readers.file import MarkdownReader
from llama_index.core.schema import Document
import re
import frontmatter
from pathlib import Path


class ObsidianMarkdownReader(MarkdownReader):
    """Obsidian .md 文件读取器，处理 wikilink/callout/embed/frontmatter。"""

    def load_data(self, file_path, extra_info=None, fs=None):
        file_path = Path(file_path)
        post = frontmatter.load(file_path)
        content = post.content
        metadata = dict(post.metadata)

        content = self._strip_wikilinks(content)
        content = self._strip_callouts(content)
        content = self._strip_embeds(content)

        extra_info = extra_info or {}
        extra_info.update({
            "file_name": file_path.name,
            "title": metadata.get("title", file_path.stem),
            "tags": metadata.get("tags", []),
            "source": str(file_path),
        })

        return [Document(text=content, metadata=extra_info)]

    def _strip_wikilinks(self, text: str) -> str:
        # 注意：group(1) 必须排除 '|'，否则 [[A|B]] 中 group(1) 会贪婪吞掉 "A|B"
        return re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]',
                      lambda m: m.group(2) or m.group(1), text)

    def _strip_callouts(self, text: str) -> str:
        return re.sub(r'^>\s*\[!\w+\]\s*', '> ', text, flags=re.MULTILINE)

    def _strip_embeds(self, text: str) -> str:
        return re.sub(r'!\[\[[^\]]+\]\]', '', text)
