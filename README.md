# 全域智联 Home Assistant 集成 0.1.2

这是与 OmniSpace CYD 固件 `qyzl.cyd.prototype/1` 配套的实验室首版集成。CYD 固件当前只能控制板载 RGB 指示灯并上报诊断数据；它不控制房间灯具、空调或其他外设。

## 安装

### 通过 HACS 安装

1. 在 HACS 的集成页面打开右上角菜单，选择“自定义存储库”。
2. 填入此 GitHub 仓库地址，类别选择“集成”，然后添加。
3. 搜索并下载“全域智联”，重启 Home Assistant。

重启后，前往“设置 → 设备与服务 → 添加集成”，搜索“全域智联”。

### 手动安装

将 `custom_components/quanyu_zhilian` 复制到 HA OS 的 `/config/custom_components/quanyu_zhilian`，然后重启 Home Assistant。MQTT 集成必须已配置并连接到 CYD 使用的同一 Broker。工程不修改 HA Core 或 HA OS。

也可解压 `dist/quanyu_zhilian-0.1.1.zip`，将其中的 `custom_components` 目录合并到 `/config`。安装包仅包含 Python/JSON 源码及说明，不包含测试缓存或凭据。运行 `python build_release.py` 可重新生成安装包及 SHA256。

## 添加网关

1. 通过 USB 串口配置 CYD。`gateway_id` 可从屏幕 DIAG 页或串口 `status` 读取。
2. 在 Broker 中创建 CYD 独立账户及 topic ACL。此固件用人工预置账号和 token，不支持自动短码配对。
3. 在 HA 中添加“全域智联”集成，输入 gateway ID、固件内相同的 `controller_id` 和 `binding_token`，并选择房间 Area。
4. 集成订阅 hello/state/ack/config_ack/availability，完成控制器心跳与房间配置 ACK 后才开放控制实体。

网关 ID 格式为 `cyd_` 加 12 位小写十六进制字符。令牌需为 32 至 128 字节，且和固件配置完全一致。房间名限制为 32 UTF-8 字节；超长时集成会拒绝控制，不会截断名称。

## 实体

- 在线、控制就绪、固件、运行时间、RSSI、堆内存、重启原因、传输模式、最后通信及配置/命令结果。
- 板载 RGB 选择器和诊断请求按钮。命令只发送一次并等待回执；5 秒无回执报告 `RESULT_UNKNOWN`，不会自动重发。
- 红外学习开始/停止按钮和最近红外信号传感器。传感器属性包含协议、位数、载波频率和原始波形；捕获也会触发 `quanyu_zhilian_ir_captured` 事件。学习最长持续 30 秒。
- 红外原始波形发送通过 `quanyu_zhilian.send_ir_raw` 服务调用，参数为 `gateway_id`、`raw` 和可选的 `frequency_khz`。回执只确认 CYD 已发出波形，不代表被控设备执行成功。
- RGB 状态的置信度是 `output_level_only`，代表固件设置的 GPIO 输出状态，不代表肉眼或外部设备反馈。

设备 Area 是房间权威来源。添加时可预选 Area；之后修改设备的 Area 会同步房间名称到 CYD。Area 名称无法通过 UTF-8 长度校验时，配置同步会停止并显示错误。

## 安全边界和已知限制

- 该原型协议没有遥测签名。集成按 MQTT ACL 作为信任边界，并校验 schema、gateway ID、boot ID、消息序号和会话。必须给每台 CYD 单独账户并限制其 topic；禁止让不可信客户端发布到网关 topic。
- Broker retained 的 hello/state/ACK 会被忽略。CYD 0.1.4 起以非 retained 方式周期发送 hello/state，让配置探测能识别新鲜在线设备；旧 retained 状态仍不能让设备显示在线。
- HA 每 10 秒发送控制器心跳，超过 30 秒的遥测视为离线。Broker 在线状态和网关在线状态分开处理。
- HA MQTT API 的 QoS 1 发布调用不返回设备执行 ACK；集成只以固件 `ack` 为准。命令不 retained。当前固件没有设备侧绝对截止时间；集成不自动重发未知结果的命令。仅在可信本地网络测试红外收发。
- 固件当前 uplink 是 QoS 0，配置只保存在 RAM，重启后必须由集成重新同步。不能据此宣称控制达到端到端 QoS 1。
- 绑定令牌随出站 MQTT 消息发送，Broker ACL 和 TLS 保护链路是必要条件。实验固件明文 MQTT 仅限隔离环境板载灯测试；不得用于真实设备控制。
- 集成本身不记录 payload。HA MQTT 的 DEBUG 日志可能包含完整出站消息和令牌；避免在真实令牌环境启用该日志或将日志公开。诊断导出隐藏绑定令牌、网关 ID、控制器 ID 和初始 Area ID。
- 配置流程需要网关在线并在 25 秒内完成状态与配置 ACK。未知固件版本/schema 会被拒绝。
- 当前支持固件版本 `0.1.0`、`0.1.1`、`0.1.3` 和 `0.1.4`（同一原型协议）。没有凭据重配界面、自动发现或外部设备适配；修改令牌/控制器 ID 暂需删除集成并按新固件配置重新添加。删除集成不会清除 CYD 的 NVS 或 Broker 账户。

## 开发验证

状态机测试（仅使用 Python 标准库）：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
```

完整 Home Assistant 运行时集成测试需在和树莓派相同 Core 版本的 HA 开发环境中执行。当前工作区没有树莓派已安装 Core 版本信息，`G:\HA\core-dev` 的 `2026.11.0.dev0` 是开发快照，不代表设备版本。

本地已验证：14 项协议状态机回归测试、Python 语法检查、Ruff 静态检查和 JSON 解析。尚未验证：HA 中实际加载/配置流程、树莓派 Broker/CYD 端到端控制、上板断线恢复和长时间运行。

HA 现场联调顺序：确认 Core 版本及 MQTT 配置 → 安装集成并重启 → 添加已配网 CYD → 查看 Area/控制就绪 → 选择绿灯并观察 GPIO/实物输出 → 断开节点及 Broker 检查 unavailable/结果未知 → 重启节点和 HA 检查重新握手。必须区分状态机测试通过、GPIO 回执和实物输出三种证据。
