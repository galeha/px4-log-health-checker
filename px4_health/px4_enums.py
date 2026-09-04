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

MAG_FIELD_DISTURBED_ENUM = {
    0: ("未检测到磁场受扰", "false"),
    1: ("检测到磁场受扰", "true"),
}

MAG_FAULT_ENUM = {
    0: ("磁力计未被 EKF 判定为故障", "false"),
    1: ("磁力计已被 EKF 判定为故障并停止使用", "true"),
}

INERTIAL_DEAD_RECKONING_ENUM = {
    0: ("未进入纯惯性航位推算", "false"),
    1: ("正在进行纯惯性航位推算", "true"),
}

MAG_TEST_RATIO_MARKERS = {
    1: ("达到磁力计融合检验门限", "1"),
}

MAG_DEVICE_ID_MARKERS = {
    0: ("未选择磁力计或设备 ID 未知", "0"),
}

BATTERY_WARNING_ENUM = {
    0: ("无电池告警", "BATTERY_WARNING_NONE"),
    1: ("电量低", "BATTERY_WARNING_LOW"),
    2: ("电量临界，应立即返航或中止任务", "BATTERY_WARNING_CRITICAL"),
    3: ("电量紧急，应立即降落", "BATTERY_WARNING_EMERGENCY"),
    4: ("电池完全失效", "BATTERY_WARNING_FAILED"),
    6: ("电池不健康或存在故障", "BATTERY_STATE_UNHEALTHY"),
    7: ("电池正在充电", "BATTERY_STATE_CHARGING"),
    10: ("电池温度过高", "BATTERY_WARNING_OVER_TEMPERATURE"),
}

BATTERY_VOLTAGE_MARKERS = {
    0: ("数据未知", "0 V"),
}

BATTERY_CURRENT_MARKERS = {
    -1: ("数据未知", "-1 A"),
}

BATTERY_REMAINING_MARKERS = {
    -1: ("数据未知", "-1"),
    0: ("约 0%", "0"),
    1: ("约 100%", "1"),
}

ACTUATOR_MOTOR_CONTROL_MARKERS = {
    -1: ("最大反向推力", "-1（仅可反转电机）"),
    0: ("零推力", "0"),
    1: ("最大正向推力", "1"),
}

MAG_X_AXIS_MARKER = {
    "X": ("机头向前", "FRD +X"),
}

MAG_Y_AXIS_MARKER = {
    "Y": ("机体向右", "FRD +Y"),
}

MAG_Z_AXIS_MARKER = {
    "Z": ("机体向下", "FRD +Z"),
}

PRIMARY_EKF_INSTANCE_ENUM = {
    index: (f"EKF 索引 {index}（第{label}套 EKF）", f"estimator_status[{index}]")
    for index, label in enumerate(("一", "二", "三", "四", "五", "六", "七", "八", "九"))
}

FILTER_FAULT_FLAGS = {
    0: ("无 EKF 内部故障", "无故障位"),
    1: ("磁力计 X 轴融合数值错误", "bit 0 · bad_mag_x"),
    2: ("磁力计 Y 轴融合数值错误", "bit 1 · bad_mag_y"),
    4: ("磁力计 Z 轴融合数值错误", "bit 2 · bad_mag_z"),
    8: ("航向角融合数值错误", "bit 3 · bad_hdg"),
    16: ("磁偏角融合数值错误", "bit 4 · bad_mag_decl"),
    32: ("空速融合数值错误", "bit 5 · bad_airspeed"),
    64: ("侧滑约束融合数值错误", "bit 6 · bad_sideslip"),
    128: ("光流 X 轴融合数值错误", "bit 7 · bad_optflow_X"),
    256: ("光流 Y 轴融合数值错误", "bit 8 · bad_optflow_Y"),
    512: ("加速度偏置估计异常", "bit 9 · bad_acc_bias"),
    1024: ("垂直加速度数据异常", "bit 10 · bad_acc_vertical"),
    2048: ("加速度数据削波或非对称触顶", "bit 11 · bad_acc_clipping"),
}

FILTER_FAULT_NOTE = (
    "这是位掩码，不是单选枚举：0 表示没有 EKF 内部故障；非零值可能同时包含多项，"
    "需要把已置位的数值相加。例如 3072 = 1024 + 2048，表示垂直加速度异常与加速度削波同时存在。"
    "映射依据 PX4 1.15 EKF fault_status_u 定义。"
)

FIELD_ENUMS = {
    ("vehicle_status", "nav_state"): (
        "各数字对应的飞行模式", NAV_STATE_ENUM,
        "未列出的数字按未知状态处理；映射依据 PX4 VehicleStatus 定义。",
    ),
    ("vehicle_status", "failsafe"): (
        "数字对应的失效保护状态", FAILSAFE_ENUM,
        "0 表示没有启用失效保护，1 表示已经启用失效保护。",
    ),
    ("failsafe_flags", "battery_warning"): (
        "电池告警等级", BATTERY_WARNING_ENUM,
        "该值来自所有已连接电池中最严重的 battery_status.warning。飞行器解锁后，PX4 只允许告警等级加重，"
        "不会因电压短暂恢复而降低。具体失效保护动作还取决于 COM_LOW_BAT_ACT 等参数；"
        "映射依据本机 PX4 1.15 BatteryStatus 定义。",
    ),
    ("estimator_status", "filter_fault_flags"): (
        "EKF 内部故障位掩码", FILTER_FAULT_FLAGS, FILTER_FAULT_NOTE, "bitmask",
    ),
    ("estimator_status_flags", "cs_mag_field_disturbed"): (
        "EKF 磁场受扰状态", MAG_FIELD_DISTURBED_ENUM,
        "1 表示 EKF 检测到实测磁场强度或磁倾角与预期不符，附近大电流导线、电机、磁性材料或外部磁场"
        "都可能导致该状态，并可能使 EKF 暂停使用磁力计融合；它不等同于磁力计硬件已经损坏。"
        "cs_mag_fault=1 才表示磁力计已被判定故障且不再使用。若 EKF2_MAG_CHECK 关闭或对应检查未启用，"
        "该字段为 0 也不能单独证明磁场环境一定正常。映射依据本机 PX4 1.15 EKF 定义。",
    ),
    ("estimator_status_flags", "cs_mag_fault"): (
        "EKF 磁力计故障状态", MAG_FAULT_ENUM,
        "0 表示当前没有把磁力计判定为故障；1 表示 EKF 已将磁力计判定为故障并停止使用。"
        "它比 cs_mag_field_disturbed 更严重，但仍需结合主 EKF 实例和故障发生时间判断。",
    ),
    ("estimator_status_flags", "cs_inertial_dead_reckoning"): (
        "EKF 纯惯性航位推算状态", INERTIAL_DEAD_RECKONING_ENUM,
        "1 表示 EKF 已没有继续融合能够约束水平速度漂移的观测，水平位置和速度主要依靠 IMU 惯性积分外推，"
        "误差会随持续时间累积；0 表示尚未处于这种状态，但不能单独证明定位质量良好。"
        "该状态常见于 GNSS、光流或外部视觉等水平辅助源不可用、超时或观测被拒绝，并不直接表示 IMU 硬件故障。"
        "飞行中若持续为 1，应结合 cs_gnss_pos、cs_gnss_vel、cs_opt_flow、cs_ev_pos、cs_ev_vel 及创新检验结果排查。",
    ),
    ("estimator_status", "mag_test_ratio"): (
        "磁力计创新检验比", MAG_TEST_RATIO_MARKERS,
        "这是连续比值，不是单选枚举：小于 1 通常表示创新处于融合门限内，达到或超过 1 表示达到门限。"
        "磁力计融合暂停时该值可能为 0，因此还需结合 cs_mag_field_disturbed 和 cs_mag_fault。",
        "annotation",
    ),
    ("sensor_selection", "mag_device_id"): (
        "当前选中磁力计的设备 ID", MAG_DEVICE_ID_MARKERS,
        "非零值是 PX4 设备标识，不是磁力计序号；需要与 sensor_mag.device_id 对照，才能确认当前使用哪个实例。",
        "annotation",
    ),
    ("estimator_selector_status", "primary_instance"): (
        "当前主 EKF 实例索引", PRIMARY_EKF_INSTANCE_ENUM,
        "索引从 0 开始：0 是第一套 EKF，1 是第二套，2 是第三套。"
        "它对应 estimator_status 的 multi_id，不代表固定优先级；实际可用数量请结合 instances_available。",
    ),
    ("battery_status", "voltage_v"): (
        "电池组总电压", BATTERY_VOLTAGE_MARKERS,
        "单位 V，表示整组电池的实时电压，不是单节电压；0 表示数据未知。"
        "负载增大时短暂下降属于压降，需要结合电流和电池串数判断。",
        "annotation",
    ),
    ("battery_status", "current_a"): (
        "电池实时电流", BATTERY_CURRENT_MARKERS,
        "单位 A。PX4 电池状态中通常以正值表示放电电流；-1 表示数据未知。"
        "电流越大，电池负载通常越重。",
        "annotation",
    ),
    ("battery_status", "remaining"): (
        "预计剩余电量比例", BATTERY_REMAINING_MARKERS,
        "有效范围为 0～1：1 表示约 100%，0.5 表示约 50%，0 表示约 0%；-1 表示数据未知。"
        "它是 PX4 的电量估计值，不等同于直接测得的容量。",
        "annotation",
    ),
    ("sensor_mag", "x"): (
        "磁场 X 轴分量", MAG_X_AXIS_MARKER,
        "单位 Gauss，表示磁场矢量在飞控板 FRD 坐标系 X 轴（机头向前）方向上的分量；"
        "正负号表示磁场方向，不是横滚角。sensor_mag 是校准修正前的传感器数据，"
        "PX4 后续会应用磁力计校准和估计偏置并生成 vehicle_magnetometer。",
        "annotation",
    ),
    ("sensor_mag", "y"): (
        "磁场 Y 轴分量", MAG_Y_AXIS_MARKER,
        "单位 Gauss，表示磁场矢量在飞控板 FRD 坐标系 Y 轴（机体向右）方向上的分量；"
        "正负号表示磁场方向，不是俯仰角。sensor_mag 是校准修正前的传感器数据，"
        "PX4 后续会应用磁力计校准和估计偏置并生成 vehicle_magnetometer。",
        "annotation",
    ),
    ("sensor_mag", "z"): (
        "磁场 Z 轴分量", MAG_Z_AXIS_MARKER,
        "单位 Gauss，表示磁场矢量在飞控板 FRD 坐标系 Z 轴（机体向下）方向上的分量；"
        "正负号表示磁场方向，不是偏航角。sensor_mag 是校准修正前的传感器数据，"
        "PX4 后续会应用磁力计校准和估计偏置并生成 vehicle_magnetometer。",
        "annotation",
    ),
    ("vehicle_magnetometer", "magnetometer_ga[0]"): (
        "校准后磁场 X 轴分量", MAG_X_AXIS_MARKER,
        "单位 Gauss，表示 PX4 选中的磁力计经过校准和偏置修正后，在 FRD 机体系 X 轴（机头向前）"
        "方向上的磁场分量。字段名末尾的 [0] 表示矢量 X 轴，不是第 1 个磁力计实例；"
        "topic 名称后的 [0] 才是 ULog 的 multi_id。",
        "annotation",
    ),
    ("vehicle_magnetometer", "magnetometer_ga[1]"): (
        "校准后磁场 Y 轴分量", MAG_Y_AXIS_MARKER,
        "单位 Gauss，表示 PX4 选中的磁力计经过校准和偏置修正后，在 FRD 机体系 Y 轴（机体向右）"
        "方向上的磁场分量。字段名末尾的 [1] 表示矢量 Y 轴，不是第 2 个磁力计实例；"
        "topic 名称后的 [0] 才是 ULog 的 multi_id。",
        "annotation",
    ),
    ("vehicle_magnetometer", "magnetometer_ga[2]"): (
        "校准后磁场 Z 轴分量", MAG_Z_AXIS_MARKER,
        "单位 Gauss，表示 PX4 选中的磁力计经过校准和偏置修正后，在 FRD 机体系 Z 轴（机体向下）"
        "方向上的磁场分量。字段名末尾的 [2] 表示矢量 Z 轴，不是第 3 个磁力计实例；"
        "topic 名称后的 [0] 才是 ULog 的 multi_id。",
        "annotation",
    ),
}


def enum_label(mapping: dict[int, tuple[str, str]], value: int, unknown_prefix: str = "未知状态") -> str:
    entry = mapping.get(int(value))
    return entry[0] if entry else f"{unknown_prefix}（{int(value)}）"


def field_enum(topic: str, field: str) -> dict[str, Any] | None:
    metadata = FIELD_ENUMS.get((topic, field))
    is_motor_control = (
        topic == "actuator_motors"
        and field.startswith("control[")
        and field.endswith("]")
    )
    if not metadata and is_motor_control:
        index_text = field[len("control["):-1]
        if index_text.isdigit() and 0 <= int(index_text) < 12:
            motor_number = int(index_text) + 1
            metadata = (
                f"第 {motor_number} 路电机归一化推力指令",
                ACTUATOR_MOTOR_CONTROL_MARKERS,
                f"control[{index_text}] 是控制分配器为第 {motor_number} 路电机生成的归一化推力设定值，"
                "由 PWM、DSHOT 或 UAVCAN 等 ESC 输出驱动使用；它是指令值，不是实测转速、实际推力或电流。"
                "范围为 -1～1：1 表示最大正向推力，-1 表示最大反向推力（仅可反转电机支持）；"
                "NaN 表示停转。数组索引从 0 开始，且不代表固定的飞控物理输出针脚。",
                "annotation",
            )
    if not metadata:
        return None
    title, mapping, note, *options = metadata
    kind = options[0] if options else "enum"
    return {
        "title": title,
        "note": note,
        "kind": kind,
        "values": [
            {
                "value": value,
                "label": label,
                "code": code,
                "derived_name": code.rsplit("·", 1)[-1].strip() if kind == "bitmask" and value else "",
            }
            for value, (label, code) in sorted(mapping.items())
        ],
    }
