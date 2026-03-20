import io
import json
import zipfile
from pathlib import Path

import requests
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_AGENT_DIR = Path(__file__).parent.parent.parent
_SKILLS_DIR = _AGENT_DIR / "skillsCenter" / "skills"
_LOCK_FILE = _SKILLS_DIR / ".skills_store_lock.json"
_SKILLHUB_BASE_URL = "https://lightmake.site/api/v1/download?slug={slug}"



class _DownloadSkillInput(BaseModel):
    slug: str = Field(description="要从 skillhub 下载安装的 skill 标识符，如 sql-toolkit")


class DownloadSkillTool(BaseTool):
    """
    从 skillhub 下载并安装 skill 的工具。

    当用户希望安装某个 skill 时调用，
    下载完成后自动更新 .skills_store_lock.json。
    """

    name: str = "download_skill"
    description: str = (
        "从 skillhub 下载并安装指定 skill。"
        "当用户想要安装、添加或获取某个 skill 时使用。"
        "输入 skill 的 slug 标识符，如 sql-toolkit。"
    )
    args_schema: type[BaseModel] = _DownloadSkillInput

    def _run(self, slug: str) -> str:
        zip_url = _SKILLHUB_BASE_URL.format(slug=slug)

        # 下载 zip
        try:
            resp = requests.get(zip_url, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as e:
            return f"下载失败：{e}"
        except requests.RequestException as e:
            return f"网络请求异常：{e}"

        # 解压到 skillsCenter/skills/（zip 内已含 <slug>/ 子目录）
        try:
            _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                zf.extractall(_SKILLS_DIR)
        except zipfile.BadZipFile:
            return f"下载内容不是有效的 zip 文件：{slug}"

        # 从 SKILL.md frontmatter 读取 name 和 version
        name, version = self._parse_skill_meta(slug)

        # 更新 .skills_store_lock.json
        self._update_lock(slug, name, zip_url, version)

        return f"skill '{slug}' 安装成功（version: {version}）"

    async def _arun(self, slug: str) -> str:
        return self._run(slug)

    @staticmethod
    def _parse_skill_meta(slug: str) -> tuple[str, str]:
        """从 SKILL.md frontmatter 读取 name；从 _meta.json 读取 version。"""
        skill_dir = _SKILLS_DIR / slug
        name = slug
        version = "unknown"

        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            for line in skill_md.read_text(encoding="utf-8").splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                    break

        meta_json = skill_dir / "_meta.json"
        if meta_json.exists():
            try:
                meta = json.loads(meta_json.read_text(encoding="utf-8"))
                version = meta.get("version", version)
            except json.JSONDecodeError:
                pass

        return name, version

    @staticmethod
    def _update_lock(slug: str, name: str, zip_url: str, version: str) -> None:
        """向 .skills_store_lock.json 追加或覆盖该 slug 的记录。"""
        lock: dict = {"version": 1, "skills": {}}
        if _LOCK_FILE.exists():
            try:
                lock = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        lock.setdefault("skills", {})[slug] = {
            "name": name,
            "zip_url": zip_url,
            "source": "skillhub",
            "version": version,
        }

        _LOCK_FILE.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")

