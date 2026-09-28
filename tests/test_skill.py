import ast
import re
import shutil
from importlib.metadata import version
from io import StringIO

import pytest
import yaml
from django.core.management import CommandError, call_command
from django.test import override_settings

from django_verifactu.management.commands.verifactu_skill import NAME, SOURCE, Command

# The only frontmatter fields the Agent Skills specification allows.
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def install(root, *args) -> str:
    out = StringIO()
    call_command("verifactu_skill", "--path", str(root), *args, stdout=out)
    return out.getvalue()


def skill() -> tuple[dict, str]:
    text = (SOURCE / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1]), text


def test_the_skill_follows_the_agent_skills_specification():
    meta, text = skill()
    assert set(meta) <= ALLOWED
    assert meta["name"] == NAME == SOURCE.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert 1 <= len(meta["description"]) <= 1024
    assert all(isinstance(value, str) for value in meta["metadata"].values())
    assert len(text.splitlines()) < 500


def test_the_skill_names_the_library_version_it_describes():
    meta, text = skill()
    current = version("django-verifactu")
    assert meta["metadata"]["library-version"] == current
    assert f"django-verifactu {current}." in text
    texts = [path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.md")]
    pinned = {found for text in texts for found in re.findall(r"django-verifactu==([\w.]+)", text)}
    assert pinned == {current}


def test_every_reference_is_linked_from_the_skill():
    _, text = skill()
    linked = set(re.findall(r"references/[\w.-]+\.md", text))
    present = {f"references/{path.name}" for path in (SOURCE / "references").glob("*.md")}
    assert linked == present


def test_every_python_example_is_valid_python():
    for path in SOURCE.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"```python\n(.*?)```", text, re.S):
            ast.parse(block, filename=str(path))


def test_the_skill_is_installed_where_the_agents_look(tmp_path):
    out = install(tmp_path)
    for folder in (".agents/skills", ".claude/skills"):
        target = tmp_path / folder / NAME
        assert (target / "SKILL.md").read_bytes() == (SOURCE / "SKILL.md").read_bytes()
        assert str(target) in out


def test_only_the_chosen_agents_get_it(tmp_path):
    install(tmp_path, "--agent", "kiro")
    assert (tmp_path / ".kiro/skills" / NAME / "SKILL.md").is_file()
    assert not (tmp_path / ".agents").exists()


def test_installing_again_replaces_a_stale_copy(tmp_path):
    install(tmp_path)
    stale = tmp_path / ".agents/skills" / NAME / "references" / "old.md"
    stale.write_text("stale", encoding="utf-8")
    with pytest.raises(CommandError, match="out of date"):
        install(tmp_path, "--check")
    install(tmp_path)
    assert not stale.exists()
    assert "up to date" in install(tmp_path, "--check")


def test_a_missing_copy_is_out_of_date(tmp_path):
    with pytest.raises(CommandError, match="out of date"):
        install(tmp_path, "--check")


def test_a_folder_that_is_not_the_skill_is_never_replaced(tmp_path):
    foreign = tmp_path / ".claude/skills" / NAME
    foreign.mkdir(parents=True)
    (foreign / "notes.md").write_text("mine", encoding="utf-8")
    with pytest.raises(CommandError, match="not the django-verifactu skill"):
        install(tmp_path)
    assert (foreign / "notes.md").read_text(encoding="utf-8") == "mine"
    assert not (tmp_path / ".agents").exists()


def test_the_default_root_is_the_git_repository(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    project = tmp_path / "backend"
    project.mkdir()
    monkeypatch.chdir(project)
    call_command("verifactu_skill", stdout=StringIO())
    assert (tmp_path / ".agents/skills" / NAME / "SKILL.md").is_file()


def test_it_installs_before_verifactu_is_configured(tmp_path):
    with override_settings(VERIFACTU={"PRODUCTION": "yes"}):
        Command().run_from_argv(["manage.py", "verifactu_skill", "--path", str(tmp_path)])
    assert (tmp_path / ".agents/skills" / NAME / "SKILL.md").is_file()


def test_a_linked_folder_is_never_replaced(tmp_path):
    install(tmp_path / "elsewhere", "--agent", "kiro")
    link = tmp_path / ".agents/skills" / NAME
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "elsewhere/.kiro/skills" / NAME)
    with pytest.raises(CommandError, match="symbolic link"):
        install(tmp_path)
    assert link.is_symlink() and not (tmp_path / ".claude").exists()


def test_a_failed_copy_keeps_the_installed_skill(tmp_path, monkeypatch):
    install(tmp_path, "--agent", "kiro")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copytree", fail)
    with pytest.raises(OSError, match="disk full"):
        install(tmp_path, "--agent", "kiro")
    monkeypatch.undo()
    assert "up to date" in install(tmp_path, "--agent", "kiro", "--check")
