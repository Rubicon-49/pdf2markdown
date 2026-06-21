import pytest

from pdf2markdown.utils import find_project_root


def test_find_project_root_returns_project_root():
    root = find_project_root()
    assert (root / "pyproject.toml").exists()

def test_find_project_root_walks_up_from_nested_anchor():
    nested = find_project_root() / "src" / "pdf2markdown" / "utils.py"
    assert find_project_root(nested) == find_project_root()

def test_find_project_root_raises_when_no_pyproject(tmp_path):
    anchor = tmp_path / "no_project_here" / "file.py"
    anchor.parent.mkdir()
    anchor.write_text("")
    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        find_project_root(anchor)
