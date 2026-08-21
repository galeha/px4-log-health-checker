from __future__ import annotations

from typing import Any


NAV_STATE_ENUM = {
    0: ("手动模式", "MANUAL"),
    1: ("定高模式", "ALTCTL"),
    2: ("定点模式", "POSCTL"),
    3: ("自动任务", "AUTO_MISSION"),
    4: ("自动悬停", "AUTO_LOITER"),
    5: ("自动返航", "AUTO_RTL"),
    6: ("慢速位置控制", "POSITION_SLOW"),
    7: ("保留状态", "FREE5"),
    8: ("保留状态", "FREE4"),
    9: ("保留状态", "FREE3"),
    10: ("特技模式", "ACRO"),
    11: ("保留状态", "FREE2"),
    12: ("下降模式", "DESCEND"),
    13: ("终止飞行", "TERMINATION"),
    14: ("Offboard 模式", "OFFBOARD"),
    15: ("自稳模式", "STAB"),
    16: ("保留状态", "FREE1"),
    17: ("自动起飞", "AUTO_TAKEOFF"),
    18: ("自动降落", "AUTO_LAND"),
    19: ("自动跟随目标", "AUTO_FOLLOW_TARGET"),
    20: ("精确降落", "AUTO_PRECLAND"),
    21: ("环绕模式", "ORBIT"),
    22: ("VTOL 自动起飞", "AUTO_VTOL_TAKEOFF"),
    23: ("外部模式 1", "EXTERNAL1"),
    24: ("外部模式 2", "EXTERNAL2"),
    25: ("外部模式 3", "EXTERNAL3"),
    26: ("外部模式 4", "EXTERNAL4"),
    27: ("外部模式 5", "EXTERNAL5"),
    28: ("外部模式 6", "EXTERNAL6"),
    29: ("外部模式 7", "EXTERNAL7"),
    30: ("外部模式 8", "EXTERNAL8"),
    31: ("状态上限标记", "MAX"),
}

FAILSAFE_ENUM = {
    0: ("未启用失效保护", "false"),
    1: ("已启用失效保护", "true"),
}

FIELD_ENUMS = {
    ("vehicle_status", "nav_state"): ("各数字对应的飞行模式", NAV_STATE_ENUM),
    ("vehicle_status", "failsafe"): ("数字对应的失效保护状态", FAILSAFE_ENUM),
}


def enum_label(mapping: dict[int, tuple[str, str]], value: int, unknown_prefix: str = "未知状态") -> str:
    entry = mapping.get(int(value))
    return entry[0] if entry else f"{unknown_prefix}（{int(value)}）"


def field_enum(topic: str, field: str) -> dict[str, Any] | None:
    metadata = FIELD_ENUMS.get((topic, field))
    if not metadata:
        return None
    title, mapping = metadata
    return {
        "title": title,
        "values": [
            {"value": value, "label": label, "code": code}
            for value, (label, code) in sorted(mapping.items())
        ],
    }
