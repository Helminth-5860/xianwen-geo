# XW-0420 检测进度页面

进度页的稳定路由是 `/geo/detections/{detectionId}`。页面刷新、关闭标签页或离开后重新打开时，仅依赖 URL 中的 detection job ID，从服务端重新读取事实，不保存关键执行状态到浏览器本地状态。

总体进度沿用 `GeoDetectionJob.progress_percent`：已终结调用数除以计划问题数与所选模型数形成的调用矩阵。成功、失败和取消是终结调用；排队、执行和重试等待不是终结调用。前端不使用计时器估算进度。

模型卡片来自本次 `GeoDetectionModelRun` 快照，并沿用 `queued`、`running`、`partial`、`succeeded`、`failed`、`cancelled`。调用超时最终按现有执行语义归入失败调用，不创建前端 timeout shadow 状态。本次选择少于八个模型时只展示实际选择的模型。

每个所选模型卡片会显式展示真实 `completed_calls / planned_calls`，并保留成功、失败和取消调用数量。

额度摘要直接读取 detection job 绑定的 `QuotaHoldGroup`：`requested_amount` 显示为计划／冻结，`consumed_amount` 显示为实际扣除，`released_amount` 显示为返还／释放，`status` 显示待结算、部分结算或已结算。前端不推断点数。

页面使用已有 job detail 和 model-progress 只读 API。非终态 `queued`、`running` 每 3 秒轮询；终态 `partial`、`succeeded`、`failed`、`cancelled` 停止自动轮询。卸载页面会清除计时器，加载错误可人工重试。两个 API 均按当前认证用户过滤 detection job，越权与不存在统一返回 404。
