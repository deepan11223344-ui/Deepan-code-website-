"""
Skill Manager for DeepanCode.
Sandboxed: size-capped .md imports, traversal-safe names, bounded prompt
injection with prompt-injection scrubbing of skill bodies.
"""

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("deepans_code.skills")

# Path to store enabled skills state
CONFIG_DIR = Path.home() / ".deepans-code"
ENABLED_SKILLS_FILE = CONFIG_DIR / "enabled_skills.json"

# Sandbox bounds.
MAX_SKILL_BYTES = 64 * 1024  # 64KB per .md import
MAX_SKILL_NAME_LEN = 64
MAX_FRONTMATTER_NAME = 64
MAX_FRONTMATTER_DESC = 256
MAX_SKILLS_ENABLED = 10
MAX_SKILL_CHARS_FOR_PROMPT = 12000  # per skill body
MAX_TOTAL_SKILL_CHARS = 48000  # total prompt injection
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")


class SkillManager:
    """Manages agent skills imported from .md files."""

    def __init__(self, skills_dir: Path = None):
        self.skills_dir = Path(skills_dir) if skills_dir else Path(__file__).parent / "skills"
        self.enabled_skills: List[str] = []
        self._initialized = False
        # No filesystem I/O at import: lazy init on first use (test isolation).

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        try:
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            from deepans_code.permissions import restrict_dir
            restrict_dir(self.skills_dir)
        except OSError as e:
            logger.error(f"Could not create skills dir: {e}")
            raise
        self.enabled_skills = self._load_enabled()
        self._initialized = True

    def _load_enabled(self):
        """Load list of enabled skill names from config (validated)."""
        try:
            if ENABLED_SKILLS_FILE.exists():
                with open(ENABLED_SKILLS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw = data.get("enabled", [])
                    if isinstance(raw, list):
                        valid = [s for s in raw if isinstance(s, str) and _NAME_RE.match(s)]
                        return valid[:MAX_SKILLS_ENABLED]
        except Exception:
            pass
        return []

    def _save_enabled(self):
        """Save enabled skills list to config (atomic, restricted)."""
        from deepans_code.permissions import atomic_write
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"enabled": self.enabled_skills}, indent=2).encode("utf-8")
        atomic_write(ENABLED_SKILLS_FILE, payload)

    def _sanitize_name(self, filename):
        """Convert filename to valid skill name (lowercase, hyphens)."""
        name = Path(filename).stem
        name = name.lower()
        name = re.sub(r'[^a-z0-9\-]', '-', name)
        name = re.sub(r'-+', '-', name)
        name = name.strip('-')
        return name[:MAX_SKILL_NAME_LEN]

    def _skill_dir_for(self, skill_name: str) -> Path:
        """Resolve + validate a skill dir. Raises ValueError on traversal."""
        if not isinstance(skill_name, str) or not _NAME_RE.match(skill_name):
            raise ValueError(f"Invalid skill name: {skill_name!r}")
        target = (self.skills_dir / skill_name).resolve()
        base = self.skills_dir.resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"Skill path escapes skills dir: {skill_name!r}")
        return target

    def list_skills(self):
        """List all available skills."""
        self._ensure_init()
        skills = []
        if not self.skills_dir.exists():
            return skills

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if skill_dir.is_dir() and not skill_dir.is_symlink():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists() and not skill_file.is_symlink():
                    try:
                        content = skill_file.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    name, description = self._parse_frontmatter(content)
                    skill_name = name or skill_dir.name
                    if not _NAME_RE.match(skill_name):
                        skill_name = skill_dir.name
                    skills.append({
                        "name": skill_name,
                        "description": description or "No description",
                        "path": str(skill_file),
                        "enabled": skill_name in self.enabled_skills
                    })
        return skills

    def _parse_frontmatter(self, content):
        """Parse YAML frontmatter from skill content (bounded)."""
        name = ""
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1][:2048]  # bound parse work
                for line in frontmatter.strip().split("\n"):
                    if line.strip().startswith("name:"):
                        name = line.split(":", 1)[1].strip()[:MAX_FRONTMATTER_NAME]
                    elif line.strip().startswith("description:"):
                        description = line.split(":", 1)[1].strip()[:MAX_FRONTMATTER_DESC]

        return name, description

    def import_skill(self, file_path):
        """Import a .md file as a skill (size-capped, symlink-safe)."""
        self._ensure_init()
        try:
            source = Path(file_path)
            if source.is_symlink():
                return {"success": False, "error": "Symlink sources not allowed"}
            if not source.exists() or not source.is_file():
                return {"success": False, "error": f"File not found: {file_path}"}

            if not source.suffix.lower() == '.md':
                return {"success": False, "error": "Only .md files can be imported as skills"}

            if source.stat().st_size > MAX_SKILL_BYTES:
                return {"success": False, "error": f"Skill file too large ({MAX_SKILL_BYTES}B max)"}

            try:
                content = source.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {"success": False, "error": "Skill file must be valid UTF-8"}
            if len(content.encode("utf-8")) > MAX_SKILL_BYTES:
                return {"success": False, "error": f"Skill file too large ({MAX_SKILL_BYTES}B max)"}
            skill_name = self._sanitize_name(source.name)

            if not skill_name or not _NAME_RE.match(skill_name):
                return {"success": False, "error": "Could not generate valid skill name from filename"}

            try:
                skill_dir = self._skill_dir_for(skill_name)
            except ValueError as e:
                return {"success": False, "error": str(e)}
            skill_dir.mkdir(parents=True, exist_ok=True)

            name, description = self._parse_frontmatter(content)

            if not content.startswith("---"):
                frontmatter = f"---\nname: {skill_name}\ndescription: {description or 'Imported skill'}\n---\n\n"
                content = frontmatter + content

            from deepans_code.permissions import atomic_write
            skill_file = skill_dir / "SKILL.md"
            atomic_write(skill_file, content.encode("utf-8"))

            return {
                "success": True,
                "name": skill_name,
                "path": str(skill_file)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def enable_skill(self, skill_name):
        """Enable a skill to be included in agent context."""
        self._ensure_init()
        try:
            skill_dir = self._skill_dir_for(skill_name)
            if not skill_dir.exists():
                return {"success": False, "error": f"Skill '{skill_name}' not found"}

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                return {"success": False, "error": f"Skill '{skill_name}' has no SKILL.md"}

            if skill_name not in self.enabled_skills:
                if len(self.enabled_skills) >= MAX_SKILLS_ENABLED:
                    return {"success": False, "error": f"Too many enabled skills ({MAX_SKILLS_ENABLED} max)"}
                self.enabled_skills.append(skill_name)
                self._save_enabled()

            return {"success": True, "message": f"Skill '{skill_name}' enabled"}
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def disable_skill(self, skill_name):
        """Disable a skill from being included in agent context."""
        self._ensure_init()
        try:
            if not isinstance(skill_name, str) or not _NAME_RE.match(skill_name):
                return {"success": False, "error": f"Invalid skill name: {skill_name!r}"}
            if skill_name in self.enabled_skills:
                self.enabled_skills.remove(skill_name)
                self._save_enabled()

            return {"success": True, "message": f"Skill '{skill_name}' disabled"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_skill(self, skill_name):
        """Remove a skill by name (traversal-safe rmtree)."""
        self._ensure_init()
        try:
            skill_dir = self._skill_dir_for(skill_name)
            if not skill_dir.exists():
                return {"success": False, "error": f"Skill '{skill_name}' not found"}

            if skill_name in self.enabled_skills:
                self.enabled_skills.remove(skill_name)
                self._save_enabled()

            # Re-verify containment after resolve (TOCTOU guard) before rmtree.
            resolved = skill_dir.resolve()
            base = self.skills_dir.resolve()
            if resolved == base or base not in resolved.parents:
                return {"success": False, "error": "Refusing to remove outside skills dir"}
            shutil.rmtree(resolved)
            return {"success": True}
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_skill_content(self, skill_name, max_chars: int = MAX_SKILL_CHARS_FOR_PROMPT) -> Optional[str]:
        """Get the (bounded) content of a skill."""
        self._ensure_init()
        try:
            skill_dir = self._skill_dir_for(skill_name)
        except ValueError:
            return None
        skill_file = skill_dir / "SKILL.md"
        try:
            if skill_file.exists() and skill_file.is_file() and not skill_file.is_symlink():
                content = skill_file.read_text(encoding="utf-8")
                return content[:max_chars]
        except (OSError, UnicodeDecodeError):
            pass
        return None

    def get_enabled_skills_content(self):
        """Get concatenated, scrubbed content of enabled skills for the system prompt."""
        self._ensure_init()
        if not self.enabled_skills:
            return ""

        from deepans_code.security import InputSanitizer
        scrubber = InputSanitizer()
        sections = []
        total = 0
        for skill_name in self.enabled_skills[:MAX_SKILLS_ENABLED]:
            content = self.get_skill_content(skill_name)
            if content:
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                # Scrub prompt-injection directives from untrusted .md bodies.
                content = scrubber.sanitize(content[:MAX_SKILL_CHARS_FOR_PROMPT], strict=True)
                if total + len(content) > MAX_TOTAL_SKILL_CHARS:
                    remaining = MAX_TOTAL_SKILL_CHARS - total
                    if remaining > 0:
                        sections.append(
                            f"=== SKILL: {skill_name} ===\n{content[:remaining]}\n... (truncated)")
                    break
                sections.append(f"=== SKILL: {skill_name} ===\n{content}\n=== END SKILL: {skill_name} ===")
                total += len(content)

        return "\n\n".join(sections)


skill_mgr = SkillManager()
