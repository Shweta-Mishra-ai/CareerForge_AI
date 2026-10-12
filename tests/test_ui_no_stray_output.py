"""Streamlit's "magic" prints any bare expression statement that is not a plain call.

`a() if x else b()` written as a statement printed a stray `None` at the bottom of the Jobs page and no test noticed,
because AppTest does not apply magic. So the source of every UI module is checked directly: the only bare expression
statements allowed are plain calls and docstrings.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*(ROOT / "careerforge" / "ui").rglob("*.py"), ROOT / "app.py"])
ALLOWED = (ast.Call, ast.Await)


def bare_expressions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            value = node.value
            is_docstring = isinstance(value, ast.Constant) and isinstance(value.value, str)
            if (
                not isinstance(value, ALLOWED)
                and not is_docstring
                and not (isinstance(value, ast.Constant) and value.value is Ellipsis)
            ):
                yield node


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_bare_expression_statements(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = [f"line {n.lineno}: {ast.unparse(n)[:70]}" for n in bare_expressions(tree)]
    assert found == [], found


def test_the_check_really_detects_the_jobs_page_bug():
    src = "def f(view):\n    _find() if view == 'a' else _tracker()\n"
    assert len(list(bare_expressions(ast.parse(src)))) == 1
    assert list(bare_expressions(ast.parse("def f():\n    '''doc'''\n    st.write(1)\n    x = 1\n"))) == []
