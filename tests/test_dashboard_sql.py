"""仪表板的 SQL 卫生：**带值的查询必须走 `params`，不许拼字符串。**

审查报告 E2：视图里曾有 11 处 `f"... WHERE r.driver='{selected_driver}'"`。
那些插值源当前都取自库内可信值，所以不是已可利用的注入 —— 但它是
"哪天加个输入框就变成真注入"的地雷。改掉 11 处只是治了这次的病；
这个测试治的是**以后还会长出来的那批**。

## 判据

扫 `query(...)` 的调用：

1. 第一个实参是**普通字符串**（不是 f-string）→ 通过。
2. 第一个实参是 f-string → 逐个看插进去的表达式：
   - 名字在 `INT_SAFE` 里（年份、轮次这类**天生是整数**的上下文变量）→ 通过；
   - 名字以 `_SQL` 结尾（`FINISHED_SQL` / `DNF_SQL`，是**代码常量 SQL 片段**、
     不是值，本来就无法参数化）→ 通过；
   - 名字在 `PLACEHOLDER_BUILDERS` 里（由 `len()` 生成的 `?` 串，与数据无关）→ 通过；
   - 其余一律失败，并给出改成 `params` 的提示。

这是**白名单**，所以是 fail-closed：以后新写一个 `{selected_track}` 这种变量名，
测试会红，除非显式加进上面的集合（那一刻你被迫想一遍"这真的安全吗"）。
"""

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASH = ROOT / "src" / "dashboard"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 天生是整数的上下文变量 —— 只能参与拼 SQL 的这一类。
INT_SAFE = {
    "year", "selected_round", "round", "rnd", "round_num", "n", "i",
}

# 由 `len()` 生成的 `?` 占位符串（例如 `",".join("?" * len(ds))`）。
# 与数据内容无关，放行；但要显式列在这里，不能靠命名巧合。
PLACEHOLDER_BUILDERS = {"ph", "placeholders"}

# `*_SQL` 结尾的常量是 SQL **片段**，不是值 —— 无法参数化，必须拼。
SQL_CONST_SUFFIX = "_SQL"


def _iter_query_calls():
    for path in sorted(DASH.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "query"
                    and node.args):
                yield path, node, node.args[0]


def _interpolated_names(fstring: ast.JoinedStr) -> set[str]:
    """f-string 里插进去的**名字**（含 `f(x)` 这类调用里的名字）。"""
    names: set[str] = set()
    for part in fstring.values:
        if not isinstance(part, ast.FormattedValue):
            continue
        for sub in ast.walk(part.value):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
    return names


def test_query_calls_with_values_use_params():
    offences = []
    for path, node, sql_arg in _iter_query_calls():
        if not isinstance(sql_arg, ast.JoinedStr):
            continue                      # 普通字符串，安全
        for name in _interpolated_names(sql_arg):
            if (name in INT_SAFE or name in PLACEHOLDER_BUILDERS
                    or name.endswith(SQL_CONST_SUFFIX)):
                continue
            offences.append(f"{path.relative_to(ROOT)}:{node.lineno} 插入了 {name!r}")
    assert not offences, (
        "这些 query() 把变量拼进了 SQL。带值的查询请改用 params：\n"
        "    query('... WHERE year = ? AND driver = ?', (year, driver))\n"
        "若确实是整数上下文变量 / `*_SQL` 常量 / `?` 占位符生成器，\n"
        "请把它显式加进本文件顶部的白名单并注明理由。\n  - "
        + "\n  - ".join(offences)
    )


def test_no_use_container_width_left():
    """`use_container_width` 已被 Streamlit 1.57 弃用、计划 2025-12-31 移除。

    29 处已迁到 `width="stretch"`。这条守住不让它长回来。
    """
    hits = []
    for path in sorted(DASH.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "use_container_width" in line:
                hits.append(f"{path.relative_to(ROOT)}:{i}")
    assert not hits, (
        "`use_container_width` 是弃用参数（Streamlit 1.57 起），请改用 "
        '`width="stretch"` / `width="content"`：\n  - ' + "\n  - ".join(hits)
    )


@pytest.mark.parametrize("fname", ["common.py"])
def test_query_accepts_params(fname):
    """`query()` 必须带 `params` 形参 —— 否则上面的白名单无从落地。"""
    text = (DASH / fname).read_text(encoding="utf-8")
    tree = ast.parse(text)
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "query"]
    assert found, f"{fname} 里找不到 query()"
    args = [a.arg for a in found[0].args.args]
    assert "params" in args, f"query() 缺 params 形参，当前是 {args}"
    defaults = found[0].args.defaults
    assert defaults, "params 必须有默认值 ()（既有调用点才能不动）"
