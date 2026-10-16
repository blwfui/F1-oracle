"""核验入口 `scripts/verify_claims.py` 的回归测试 —— 钉住「尺子的尺子」。

审查方抓到过的那一处，正是这个文件要防的病：

    docstring 自称「与 README 里的字符串逐条比对」，实现里**一行都没读 README.md**，
    文档值是写死的 `check(..., 0.6082)`。于是 README 漂了，尺子照样报全绿 ——
    比没有尺子更糟，因为它给了一种虚假的安全感。

这几条测试**不碰数据库、不联网**，只钉住四件事：

1. **文档值必须来自文件。** 把 README 抄一份、改掉其中一个数字，解析器必须跟着变。
   常量版会继续返回旧值 —— 这条测试就是为了让它红。
2. **锚点必须唯一命中。** 锚点选得不独特，就会量到别的行，得到"碰巧对上"的假绿。
3. **锚点缺失必须响亮。** README 改了措辞而锚点表没跟上时，要变成 ❌ 而不是静默跳过。
4. **容差没有调宽的手柄。** 容差由文档自身精度决定：写 4 位就只准差 5e-5。
   真实的文档漂移（`0.0238` vs `0.0245`，差 7e-4）必须**过不去**。
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_claims as V  # noqa: E402

README_TEXT = V.README_PATH.read_text(encoding="utf-8")


def _mutate(key: str, new_value: str) -> str:
    """把 README 里某条声明的数字换成别的 —— 用来证明解析器真在读文件。"""
    pat, grp = V.PATTERNS[key]
    m = re.search(pat, README_TEXT)
    assert m, f"锚点 {key} 在 README 里没命中，测试样本需要同步"
    return README_TEXT[:m.start(grp)] + new_value + README_TEXT[m.end(grp):]


# ── 1. 文档值来自 README，不是脚本里的常量 ───────────────────
def test_doc_values_are_read_from_the_file(tmp_path):
    src = _mutate("rho_pre_naive", "0.1234")
    assert src != README_TEXT
    p = tmp_path / "README.md"
    p.write_text(src, encoding="utf-8")
    assert V.Doc(p).num("rho_pre_naive") == pytest.approx(0.1234)


def test_mutating_readme_makes_the_check_fail(tmp_path):
    """端到端一点：改了 README 的数字 → 同一实测值必须判 ❌。"""
    p = tmp_path / "README.md"
    p.write_text(_mutate("rho_pre_mine", "0.9999"), encoding="utf-8")
    d = V.Doc(p)
    assert d.num("rho_pre_mine") == pytest.approx(0.9999)
    assert abs(0.6082 - d.num("rho_pre_mine")) > d.tol("rho_pre_mine")


# ── 2. 锚点唯一性 ───────────────────────────────────────────
def test_every_anchor_hits_exactly_once():
    dup = [(k, len(re.findall(p, README_TEXT)))
           for k, (p, _g) in V.PATTERNS.items()
           if len(re.findall(p, README_TEXT)) != 1]
    assert dup == [], f"锚点未唯一命中（会量到别的行 / 彻底失效）：{dup}"


def test_ambiguous_anchors_are_reported():
    d = V.Doc()
    assert d.ambiguous() == []


# ── 3. 锚点缺失要响亮 ───────────────────────────────────────
def test_missing_anchor_is_flagged_not_skipped(tmp_path):
    src = README_TEXT.replace("检验单位是 **172 场**", "检验单位变了个说法")
    assert src != README_TEXT, "测试用的锚点句已不在 README 里，需同步更新"
    p = tmp_path / "README.md"
    p.write_text(src, encoding="utf-8")
    d = V.Doc(p)
    v = d.num("lap_n")
    assert v != v, "锚点缺失必须返回 nan（→ check 判 ❌），不能返回旧值"
    assert d.missing == ["lap_n"]


def test_unknown_key_raises_instead_of_guessing():
    with pytest.raises(SystemExit):
        V.Doc().num("不存在的锚点")


# ── 4. 容差只吸收四舍五入，不吸收分歧 ───────────────────────
@pytest.mark.parametrize(("key", "tol"), [
    ("rho_pre_mine", 5e-5),   # README 写 4 位
    ("corr_dnf", 5e-4),       # README 写 3 位（−0.565）
    ("n_races_25", 0.5),      # README 写整数
])
def test_tolerance_comes_from_documented_precision(key, tol):
    d = V.Doc()
    d.num(key)
    assert d.tol(key) == pytest.approx(tol)


def test_tolerance_cannot_swallow_a_real_disagreement():
    """历史上真实发生过的那次漂移：README 0.0238 vs 实测 0.0245，差 7e-4。

    文档写 4 位 → 容差 5e-5，这个分歧必须**过不去**。
    如果哪天有人把容差改成 1e-3 来"让它绿"，这条测试会红。
    """
    d = V.Doc()
    d.num("delta_finishers")
    d.num("corr_dnf")          # 先解析，才知道 README 写了几位
    assert abs(0.0245 - 0.0238) > d.tol("delta_finishers")
    assert abs(0.5652 - 0.565) <= d.tol("corr_dnf"), "真·四舍五入必须过得去"
