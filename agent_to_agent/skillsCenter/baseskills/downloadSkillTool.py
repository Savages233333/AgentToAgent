import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_AGENT_DIR = Path(__file__).parent.parent.parent
_SKILLS_DIR = _AGENT_DIR / "skillsCenter" / "skills"
_LOCK_FILE = _SKILLS_DIR / ".skills_store_lock.json"
_WHITELIST_FILE = _AGENT_DIR / "static" / "allowed_skills.json"
_TMP_INSTALL_ROOT = _AGENT_DIR / "skillsCenter" / ".tmp_installs"


class _DownloadSkillInput(BaseModel):
    slug: str = Field(description="要从白名单来源下载安装的 skill 标识符，如 sql-toolkit")


class DownloadSkillTool(BaseTool):
    """
    从白名单来源下载并安装 skill。

    安装流程采用临时目录校验和原子替换，只有全部成功后才会更新
    skills 目录和 .skills_store_lock.json，避免安装失败时破坏现有状态。
    """

    name: str = "download_skill"
    description: str = (
        "从白名单来源下载并安装指定 skill。"
        "仅允许安装白名单中的 skill，并会校验版本、来源和文件完整性。"
        "输入 skill 的 slug 标识符，如 sql-toolkit。"
    )
    args_schema: type[BaseModel] = _DownloadSkillInput

    def _run(self, slug: str) -> str:
        try:
            whitelist_entry = self._get_whitelist_entry(slug)
        except ValueError as exc:
            return str(exc)

        installed = self._inspect_installed_skill(slug)
        if (
            installed
            and installed["version"] == whitelist_entry["version"]
            and (_SKILLS_DIR / slug).exists()
        ):
            self._update_lock(
                slug=slug,
                name=installed["name"],
                zip_url=whitelist_entry["download_url"],
                version=installed["version"],
                sha256=installed.get("sha256"),
            )
            return f"skill '{slug}' 已安装（version: {installed['version']}）"

        zip_url = whitelist_entry["download_url"]

        try:
            response = requests.get(zip_url, timeout=30)
            response.raise_for_status()
        except requests.HTTPError as exc:
            return f"下载失败：{exc}"
        except requests.RequestException as exc:
            return f"网络请求异常：{exc}"

        content = response.content
        actual_sha256 = hashlib.sha256(content).hexdigest()
        expected_sha256 = whitelist_entry.get("sha256")
        if expected_sha256 and actual_sha256 != expected_sha256:
            return f"校验失败：skill '{slug}' 的压缩包哈希不匹配"

        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        _TMP_INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(dir=_TMP_INSTALL_ROOT) as tmp_dir:
                temp_root = Path(tmp_dir)
                archive_path = temp_root / f"{slug}.zip"
                extract_root = temp_root / "extract"
                install_root = temp_root / "install"
                backup_root = temp_root / "backup"
                archive_path.write_bytes(content)
                extract_root.mkdir(parents=True, exist_ok=True)
                install_root.mkdir(parents=True, exist_ok=True)

                try:
                    with zipfile.ZipFile(archive_path) as archive:
                        self._validate_archive_members(archive, slug)
                        archive.extractall(extract_root)
                except zipfile.BadZipFile:
                    return f"下载内容不是有效的 zip 文件：{slug}"

                extracted_skill_dir = self._resolve_extracted_skill_dir(extract_root, slug)
                if extracted_skill_dir is None:
                    return f"安装失败：未找到 skill '{slug}' 的解压目录"

                metadata = self._validate_extracted_skill(extracted_skill_dir, slug, whitelist_entry)

                staged_target = install_root / slug
                shutil.copytree(extracted_skill_dir, staged_target)

                target_dir = _SKILLS_DIR / slug
                backup_dir = backup_root / slug

                if target_dir.exists():
                    backup_root.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target_dir), str(backup_dir))

                try:
                    shutil.move(str(staged_target), str(target_dir))
                    self._update_lock(
                        slug=slug,
                        name=metadata["name"],
                        zip_url=zip_url,
                        version=metadata["version"],
                        sha256=actual_sha256,
                    )
                except Exception:
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                    if backup_dir.exists():
                        shutil.move(str(backup_dir), str(target_dir))
                    raise

        except Exception as exc:
            return f"安装失败：{exc}"

        return f"skill '{slug}' 安装成功（version: {metadata['version']}）"

    async def _arun(self, slug: str) -> str:
        return self._run(slug)

    @staticmethod
    def _get_whitelist_entry(slug: str) -> dict:
        if not _WHITELIST_FILE.exists():
            raise ValueError("安装失败：skill 白名单不存在")

        try:
            data = json.loads(_WHITELIST_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"安装失败：skill 白名单损坏：{exc}") from exc

        entry = data.get("skills", {}).get(slug)
        if not entry:
            raise ValueError(f"安装失败：skill '{slug}' 不在允许安装的白名单中")

        download_url = entry.get("download_url", "")
        parsed = urlparse(download_url)
        allowed_domains = set(data.get("allowed_domains", []))
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"安装失败：skill '{slug}' 的下载地址不合法")
        if allowed_domains and parsed.netloc not in allowed_domains:
            raise ValueError(f"安装失败：skill '{slug}' 的下载来源不在白名单域名中")

        version = entry.get("version")
        if not version:
            raise ValueError(f"安装失败：skill '{slug}' 缺少白名单版本信息")

        entry["download_url"] = download_url
        entry["version"] = version
        return entry

    @staticmethod
    def _validate_archive_members(archive: zipfile.ZipFile, slug: str) -> None:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute():
                raise ValueError(f"安装失败：skill '{slug}' 压缩包包含绝对路径")
            if ".." in member_path.parts:
                raise ValueError(f"安装失败：skill '{slug}' 压缩包包含非法路径")

    @staticmethod
    def _resolve_extracted_skill_dir(extract_root: Path, slug: str) -> Path | None:
        direct_dir = extract_root / slug
        if direct_dir.is_dir():
            return direct_dir

        candidate = next(extract_root.rglob(slug), None)
        if candidate and candidate.is_dir():
            return candidate

        return None

    @staticmethod
    def _validate_extracted_skill(skill_dir: Path, slug: str, whitelist_entry: dict) -> dict:
        skill_md = skill_dir / "SKILL.md"
        meta_json = skill_dir / "_meta.json"
        if not skill_md.exists():
            raise ValueError(f"安装失败：skill '{slug}' 缺少 SKILL.md")
        if not meta_json.exists():
            raise ValueError(f"安装失败：skill '{slug}' 缺少 _meta.json")

        try:
            meta = json.loads(meta_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"安装失败：skill '{slug}' 的 _meta.json 非法：{exc}") from exc

        if meta.get("slug") != slug:
            raise ValueError(f"安装失败：skill '{slug}' 的元数据 slug 不匹配")
        if meta.get("version") != whitelist_entry["version"]:
            raise ValueError(
                f"安装失败：skill '{slug}' 的版本为 {meta.get('version')}，"
                f"不匹配白名单版本 {whitelist_entry['version']}"
            )

        name = DownloadSkillTool._parse_skill_name(skill_md) or whitelist_entry.get("name", slug)
        return {
            "name": name,
            "version": meta["version"],
        }

    @staticmethod
    def _parse_skill_name(skill_md: Path) -> str | None:
        for line in skill_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip()
        return None

    @staticmethod
    def _inspect_installed_skill(slug: str) -> dict | None:
        skill_dir = _SKILLS_DIR / slug
        skill_md = skill_dir / "SKILL.md"
        meta_json = skill_dir / "_meta.json"
        if not skill_md.exists() or not meta_json.exists():
            return None

        try:
            meta = json.loads(meta_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

        if meta.get("slug") != slug or not meta.get("version"):
            return None

        name = DownloadSkillTool._parse_skill_name(skill_md) or slug
        lock = DownloadSkillTool._read_lock()
        sha256 = lock.get("skills", {}).get(slug, {}).get("sha256")
        return {
            "name": name,
            "version": meta["version"],
            "sha256": sha256,
        }

    @staticmethod
    def _read_lock() -> dict:
        lock: dict = {"version": 2, "skills": {}}
        if not _LOCK_FILE.exists():
            return lock

        try:
            loaded = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return lock

        loaded.setdefault("version", 2)
        loaded.setdefault("skills", {})
        return loaded

    @staticmethod
    def _update_lock(slug: str, name: str, zip_url: str, version: str, sha256: str | None) -> None:
        lock = DownloadSkillTool._read_lock()
        lock["version"] = 2
        lock.setdefault("skills", {})[slug] = {
            "name": name,
            "zip_url": zip_url,
            "source": "skillhub",
            "version": version,
            "sha256": sha256,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        _LOCK_FILE.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
