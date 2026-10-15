"""主动空气动力学区段（Straight Mode）与超车模式检测点。

⚠️ 数据来源与精度
-----------------
2026 赛季起，F1 用「主动空气动力学」取代了 DRS：前后翼都能改变攻角，
在指定区段进入低阻的 Straight Mode（SM）。FIA 只公布区段所在的**弯角区间**，
不公布精确米数，因此下表是依据公开报道对弯角的描述推算的：

  - The Race, "F1 drivers can use straight mode in five places at Australian GP"
  - PlanetF1, "Australian GP track map replaces DRS with Straight Mode zones"
  - F1 官网 2026 赛道图（Albert Park 标出 5 个 SM 区）

区段边界误差约 **±100 m**。它足以说明「车跑到这一段可以放平襟翼」，
但**不能**用于秒差、进站窗口等需要精确里程的分析。
各家媒体的描述本身也有出入（一处写 T6→T9-10，另一处写 T8→T9），
这里取了更详细的那个说法。

⚠️ 规则年份
-----------
SM 与 Overtake Mode 均是 **2026 年才启用**的新规则。此前（DRS 时代）的
区段位置不同，本表**不适用** —— 所以每条赛道带 ``since`` 字段挡住更早的场次。
宁可页面上没有这一图层，也不要拿 2026 的区段去标 2023 的比赛。

表示法
------
每条赛道给若干 ``(start_m, end_m)``，单位为「距起点/终点线的米数」；
``end_m`` 可以大于赛道总长，表示该区段**跨越起点线**（例如主直道）。
"""

AERO: dict[str, dict] = {
    # 2026 澳大利亚站（Albert Park）：5 个区段，前 4 个沿用旧 DRS 区，
    # 第 5 个是新增的 T5→T6 短区；中段区段的起点比旧 DRS 更早。
    "Melbourne": {
        "since": 2026,
        "zones": [
            (4831.6, 5559.9),   # 1. 主直道（跨起点线）：T14 之后 → T1 之前
            (477.5, 1040.3),    # 2. T1 组合弯之后 → T3
            (1473.4, 1821.5),   # 3. T5 → T6（新增的短区）
            (1901.5, 3243.8),   # 4. T6 → T9/T10 连续弯（Lakeside Drive）
            (3437.7, 4059.8),   # 5. T9/T10 之后 → T11
        ],
        # Overtake Mode：检测点在倒数第二个弯（T13）之后，可在 T14 之前激活
        "overtake": {"detection": 4650.0, "activation": 4730.0},
    },
}

NOTE = "区段依据 2026 赛季公开报道对弯角的描述推算，误差约 ±100 m，非 FIA 官方米数"


def _entry(circuit_id: str, year: int) -> dict | None:
    """取出该赛道该年份适用的条目；规则生效年之前的场次一律返回 None。"""
    e = AERO.get(circuit_id)
    if not e or year < e.get("since", 9999):
        return None
    return e


def zones_for(circuit_id: str, track_length_m: float, year: int
              ) -> list[tuple[float, float]]:
    """把区段转成沿赛道的比例区间 ``[(start_frac, end_frac), ...]``。

    ``end_frac`` 可能大于 1，表示跨过起点线。年份早于规则生效年时返回空列表。
    """
    e = _entry(circuit_id, year)
    if not e or not track_length_m:
        return []
    return [(s / track_length_m, t / track_length_m) for s, t in e["zones"]]


def overtake_for(circuit_id: str, track_length_m: float, year: int) -> dict[str, float]:
    """超车模式检测点 / 激活点的位置比例。"""
    e = _entry(circuit_id, year)
    if not e or not track_length_m:
        return {}
    return {k: v / track_length_m for k, v in e.get("overtake", {}).items()}
