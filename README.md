# PX4 日志飞行健康检查器

面向普通 PX4 多旋翼用户的中文飞后检查工具。导入一份 `.ulg` 后，先查看六项健康结论，点击某项再查看曲线、原始指标、判定依据和相关 PX4 参数中文说明。

## 已实现

- 机体振动：X/Y/Z 三轴高频加速度 RMS、传感器削波和可用的 EKF 振动指标
- GPS 状态：定位类型、卫星数、EPH/EPV、干扰与欺骗状态
- 电池压降：单体电压变化、飞控告警、单体压差和动态内阻参考值
- 姿态跟踪：用四元数综合误差判定等级，详情显示横滚/俯仰/偏航实际值与目标值
- 电机输出余量：归一化电机输出 P95、峰值和接近饱和时间占比
- 磁力计异常：磁场模长与 EKF 磁场状态；动力电流或电机输出仅用于判断磁场异常是否可能与动力负载相关，判断等级会计入总评
- 全量日志曲线：检索全部带时间戳的数值字段，按单位自动或手动分图，支持悬停读数、缩放、平移、复位，以及按图独立叠加事件与告警
- 飞行事件时间线：汇总解锁、模式、起降、PX4 告警、失效保护和估计器故障，支持中文解释、原文展开、曲线联动，并可显示为健康指标图和日志曲线的时间轴标记
- 候选 v2 影子分析：显示采样率、数据覆盖率、持续异常时间段和实验性结论，但不改变当前 v1.2.0 总评
- 磁力计实验规则：优先读取校准后的 `vehicle_magnetometer`，没有可靠动力电流时才使用低可信度的电机输出代理
- 真实日志验证：人工标签清单、v1/v2 混淆矩阵、误报漏报统计和脱敏指标快照

## 启动

需要 Python 3.10 或更高版本。Windows PowerShell 中运行：

```powershell
cd D:\AI_work\px4-log-health-checker
.\run.ps1
```

脚本会自动创建并使用项目目录中的 `.venv`，检查 `numpy` 和 `pyulog`，缺少时安装 `requirements.txt`，随后打开 `http://127.0.0.1:8765`。不需要提前激活虚拟环境，也不会修改系统 Python 环境。

如果 PowerShell 首次运行时提示“禁止运行脚本”，先为当前 Windows 用户执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

确认后重新执行 `.\run.ps1`。该设置只调整当前用户的 PowerShell 脚本策略；如果设备由组织策略管理，请联系管理员，不要绕过组织限制。

也可以绕过启动脚本，明确使用项目虚拟环境运行：

```powershell
.\.venv\Scripts\python.exe app.py
```

停止服务时可以在控制台按任意键，也可以点击浏览器右上角的“退出程序”。正常关闭最后一个浏览器标签页后，本地服务也会自动退出；刷新页面不会误退出。服务退出后，尚未关闭的标签页会显示退出提示。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 构建 Windows 便携版

项目使用 PyInstaller `onedir` 模式生成无需安装 Python 的 Windows x64 便携目录。构建机必须是 Windows x64，并已通过 `run.ps1` 创建项目虚拟环境。

```powershell
cd D:\AI_work\px4-log-health-checker
.\scripts\build_windows.ps1
```

如果当前 PowerShell 执行策略不允许运行脚本，可以只为本次终端进程临时放行后构建；关闭终端后设置即失效：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\build_windows.ps1
```

构建脚本会安装固定版本的构建依赖、运行源码测试、生成便携目录，并启动打包后的程序检查健康接口和前端静态资源。产物位于：

```text
dist\PX4-Log-Health-Checker\
```

双击其中的 `PX4-Log-Health-Checker.exe` 即可启动；程序会打开默认浏览器。可以在控制台按任意键、点击页面右上角的“退出程序”，或者关闭最后一个浏览器标签页来停止服务。单独重复打包产物检查时运行：

```powershell
.\scripts\smoke_test_packaged_app.ps1
```

## 发布 GitHub Release

推送符合语义化版本格式的 `v*` Tag 后，GitHub Actions 会在 Windows x64 环境中重新安装依赖、运行测试、构建和检查便携程序，并自动发布带 SHA-256 校验文件的 GitHub Release。正式版本使用 `v1.2.0` 格式；测试版本可以使用 `v1.3.0-beta.1`，并会自动标记为 prerelease。

发布前先提交并推送全部源码修改，然后在需要发布的提交上创建 Tag：

```powershell
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
```

工作流成功后，Release 中会包含：

```text
PX4-Log-Health-Checker-v1.2.0-win64.zip
PX4-Log-Health-Checker-v1.2.0-win64.zip.sha256
```

正式 Tag 和已经发布的 Release 不应覆盖或移动；后续修复应创建新版本号。如果工作流在创建 Release 时提示权限不足，请在仓库 `Settings → Actions → General → Workflow permissions` 中允许 GitHub Actions 创建和更新仓库内容。

真实日志校准和公开 PX4 样本获取见 [validation/README.md](validation/README.md)。当前规则仍为默认 v1.2.0；候选 v2 只有在人工标注集达到验收目标后才能升级为正式规则。

## 数据与规则边界

- 所有 PX4 ULog 均可进入分析；规则目前仅针对多旋翼，固定翼、VTOL 等其他机型会显示兼容性提醒，其问题判断可能有误。
- 日志通过本机回环地址传给本地进程。为支持按需读取曲线，当前日志临时副本仅保留到选择下一份日志或服务退出；没有云端请求、账户、数据库或历史记录。
- PX4 `event` 仅使用 ULog 内嵌的事件定义离线解码；日志未内嵌定义时保留未知事件 ID，不联网下载定义文件。
- 没有检测到起飞/解锁阶段，或缺少关键主题时，显示“数据不足”，不会显示“正常”。
- 每项详情列出实际采用的 ULog topic 和字段；鼠标悬停字段名可查看中文含义、单位和计算用途。
- P10、P90、P95、P90-P10 等统计术语带有页面注解，并明确它们不是“最大值的百分比”。
- 阈值位于 `px4_health/rules_v1.json`，是首版工程判据，不代表 PX4 官方适航限制。调整阈值后应更新规则版本并重新跑测试日志。
- 候选算法位于 `px4_health/candidate_v2.py` 和 `rules_candidate_v2.json`，页面明确标记为实验性，不参与顶部总判定。
- 电池串数不可信时，工具会根据日志满电电压参数推断并在证据中明确标注。
- 本工具用于飞后维护排查，不能替代飞前检查、机体检查或飞行安全决策，也不会修改飞控参数。
