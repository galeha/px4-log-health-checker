# 真实日志验证

本目录只提交清单模板和说明，不提交原始 `.ulg`。标签必须来自飞手/维护复核，并结合 PX4 告警、传感器状态和曲线证据，不能把程序自身的结论当作真值。

## 1. 初始化本机日志清单

```powershell
python -m px4_health.validation init `
  --logs "C:\Users\Xu\Desktop\PX4日志" `
  --output validation\manifest.local.json
```

逐项填写 `review_status`、`reviewer`、`known_conditions`、五项 `labels` 和 `evidence_notes`。合法标签为 `normal`、`warning`、`severe`、`unavailable`；未复核保持 `unknown`。

## 2. 批量比较 v1 与候选 v2

```powershell
python -m px4_health.validation run `
  --manifest validation\manifest.local.json `
  --output validation\results\latest.json
```

报告包含混淆矩阵、已知严重案例检出率、正常日志严重误报率、脱敏指标快照和错误列表。没有人工标签时只生成快照，不计算验收结论。

## 3. 公开样本

可直接从 [PX4 Flight Review Public Logs](https://logs.px4.io/browse) 官方目录筛选 25 份不同车辆的多旋翼日志，其中优先选择 15 份 Good/Great：

```powershell
python scripts\download_public_logs.py `
  --official-count 25 `
  --good-count 15 `
  --output validation-data\public
```

脚本遵守官方建议的 6 秒下载间隔。也可将下载链接逐行放入 `validation/public_urls.txt`，改用 `--urls validation\public_urls.txt`。

公开样本在清单中标记 `source=px4-flight-review-public`、`license=CC-BY PX4`，仍需人工复核后才能参与阈值校准。

下载完成后，把公开日志与本地清单合并（相同 SHA256 会自动去重）：

```powershell
python -m px4_health.validation merge `
  --base validation\manifest.local.json `
  --public validation-data\public\downloaded_manifest.json `
  --output validation\manifest.local.json
```

`run` 报告中的 `calibration` 会对已复核样本做阈值网格评估。它优先排除“已知严重却判为正常”的组合，再从可行组合中选择正常样本严重误报最少、总错分最少的候选值；样本不足时只输出 `insufficient_labels`，不会擅自改写规则文件。
