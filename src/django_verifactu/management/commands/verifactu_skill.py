import shutil
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import django_verifactu

NAME = "django-verifactu"
SOURCE = Path(django_verifactu.__file__).parent / "skill" / NAME
# Checked in each agent's documentation (September 2026): .agents/skills is read by Codex,
# Cursor, Gemini CLI, GitHub Copilot and VS Code, OpenCode, Amp, Windsurf and Junie; Claude
# Code reads only .claude/skills, and Kiro only .kiro/skills.
FOLDERS = {"agents": ".agents/skills", "claude": ".claude/skills", "kiro": ".kiro/skills"}


class Command(BaseCommand):
    help = "Install the django-verifactu Agent Skill, so coding agents integrate the library well."
    # The skill teaches how to configure VERIFACTU, so installing it must not need a valid one.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--path", help="project root (default: the git repository root)")
        parser.add_argument(
            "--agent",
            action="append",
            choices=sorted(FOLDERS),
            help="skill folder to fill, repeatable (default: agents and claude)",
        )
        parser.add_argument(
            "--check", action="store_true", help="only fail if an installed copy is out of date"
        )

    def handle(self, *args, path, agent, check, **options):
        root = Path(path) if path else _repository_root(Path.cwd())
        targets = [root / FOLDERS[key] / NAME for key in agent or ["agents", "claude"]]
        if check:
            stale = [target for target in targets if _files(target) != _files(SOURCE)]
            if stale:
                paths = ", ".join(str(target) for target in stale)
                raise CommandError(f"out of date, run verifactu_skill again: {paths}")
            self.stdout.write("the django-verifactu skill is up to date")
            return
        for target in targets:
            if target.is_symlink():
                raise CommandError(f"{target} is a symbolic link, remove it or use --path")
            if target.exists() and f"name: {NAME}\n" not in _skill_text(target):
                raise CommandError(f"{target} exists and is not the django-verifactu skill")
        for target in targets:
            _install(target)
            self.stdout.write(str(target))


def _repository_root(start: Path) -> Path:
    return next((path for path in [start, *start.parents] if (path / ".git").exists()), start)


def _files(folder: Path) -> dict[str, bytes]:
    if not folder.is_dir():
        return {}
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


# The folder belongs to the library: a full copy replaces it whole, so no stale file survives
# and a failed copy leaves the installed one.
def _install(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        copy = Path(temporary) / NAME
        shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns("__pycache__"))
        if target.exists():
            shutil.rmtree(target)
        copy.rename(target)


def _skill_text(folder: Path) -> str:
    skill = folder / "SKILL.md"
    return skill.read_text(encoding="utf-8") if skill.is_file() else ""
