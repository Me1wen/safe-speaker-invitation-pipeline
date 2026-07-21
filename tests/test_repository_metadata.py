import re
from pathlib import Path

import yaml

from speaker_pipeline import __version__

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 CI
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_version_is_synchronized():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == __version__
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_github_yaml_is_parseable():
    yaml_files = sorted((ROOT / ".github").rglob("*.yml"))
    assert yaml_files
    for path in yaml_files:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict), path


def test_runtime_data_and_active_config_are_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for value in (
        "config/invitation.json",
        "config/industry_sources.csv",
        "data/*",
        "outputs/*",
    ):
        assert value in ignore


def test_public_documentation_contains_no_chinese_text():
    paths = [
        ROOT / "README.md",
        ROOT / "TEST_REPORT.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CODE_OF_CONDUCT.md",
        *sorted((ROOT / "docs").glob("*.md")),
    ]
    chinese = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
    for path in paths:
        assert not chinese.search(path.read_text(encoding="utf-8")), path
