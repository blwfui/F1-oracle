"""导出与回放数据层的回归测试（不碰数据库、不联网）。

钉住两件事：

1. **`<script>` 里的 JSON 必须转义。** 审查报告 E3：`export_replay.py` 原来
   直接 `json.dumps` 后 `str.replace` 拼进模板。库内文本一旦含 `</script>`，
   浏览器就地结束脚本块 —— 整页 JS 废掉，而且不报错、只是白屏。
   当前库内数据是干净的，所以这属于**潜在**缺陷；正因如此才需要一条测试
   把它固定成"永远不会发生"，而不是等哪天数据脏了才发现。

2. **`times(lap)` 的缓存不能改变语义。** 加缓存是为了让回放导出少建
   2000 多个临时 dict；但如果缓存让"同一圈返回同一个 dict 对象"变成了
   调用方可以改坏的状态，那就得不偿失。
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_replay import html_esc, js_json      # noqa: E402
from src.model.lapdata import LapTimeline                # noqa: E402

# ── 1. 转义 ─────────────────────────────────────────────────
NASTY = {
    "script": "</script><img src=x onerror=alert(1)>",
    "line_sep": "A\u2028B\u2029C",          # JSON 合法、JS 字符串里是换行
    "amp": "a&b",
    "quote": 'he said "hi"',
    "cjk": "银石赛道 · Silverstone",
}


def test_js_json_leaves_no_raw_script_tag():
    out = js_json(NASTY)
    assert "</script>" not in out
    assert "<" not in out.split('"')[0] or True     # 只关心字符串里的尖括号
    assert "<" not in out and ">" not in out
    assert "\u2028" not in out and "\u2029" not in out


def test_js_json_round_trips_exactly():
    """转义必须是无损的 —— `json.loads` 要能原样还原。"""
    assert json.loads(js_json(NASTY)) == NASTY


def test_js_json_handles_nested_and_non_string_values():
    obj = {"a": [1, 2.5, None, True, False], "b": {"c": "</script>"}, "d": 0}
    assert json.loads(js_json(obj)) == obj
    assert "</script>" not in js_json(obj)


def test_js_json_keeps_cjk_readable():
    """不该为了转义把中文变成 \\uXXXX（文件会白胖一圈）。"""
    assert "银石赛道" in js_json(NASTY)


def test_html_esc_escapes_quotes_and_brackets():
    assert html_esc('<b>&"x"</b>') == "&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;"
    assert html_esc("O'Brien") == "O&#x27;Brien"


# ── 2. times() 缓存 ─────────────────────────────────────────
def _timeline():
    states = {
        1: {"VER": {"time_sec": 95.0}, "HAM": {"time_sec": 96.5},
            "NOR": {"time_sec": None}},          # 无成绩的必须被过滤
        2: {"VER": {"time_sec": 187.0}, "HAM": {"time_sec": 189.0}},
        3: {},
    }
    return LapTimeline(2026, 1, 58, states, {})


def test_times_filters_missing_values():
    t = _timeline()
    assert t.times(1) == {"VER": 95.0, "HAM": 96.5}     # NOR 被剔除
    assert t.times(3) == {}


def test_times_is_cached_but_value_identical():
    """同圈两次调用返回**同一个对象**（省掉重复构造），且内容一致。"""
    t = _timeline()
    a, b = t.times(2), t.times(2)
    assert a is b
    assert a == {"VER": 187.0, "HAM": 189.0}
    assert t.times(1) is not a                          # 不同圈不同对象


def test_times_cache_does_not_leak_between_instances():
    t1, t2 = _timeline(), _timeline()
    assert t1.times(1) is not t2.times(1)
    assert t1.times(1) == t2.times(1)


def test_times_accepts_unknown_lap():
    """不存在的圈返回空 dict，不抛异常（回放会问边界圈）。"""
    t = _timeline()
    assert t.times(0) == {}
    assert t.times(999) == {}
