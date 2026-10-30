# 本地红外库

集成 0.3.1 随安装包附带完整 Flipper-IRDB 文件快照的 SQLite 索引，
8,901 个遥控器文件，301,915 条按键记录。运行时无下载、云服务或外网请求；
不增加 Python 依赖。数据库只读、按页查询，磁盘操作在 HA 的工作线程执行。

来源：https://github.com/Lucaslhm/Flipper-IRDB

固定版本：`d126fb1b6f1e114c52b4a8c19839ea65e3a9c24d`。
原始 `.ir` 字节保存在数据库中；raw 和 parsed 记录均保留，未将协议值猜测转换为波形。
快照不代表所有品牌型号或所有空调状态组合。IRext 未取得可分发的离线数据，未收录。
Arduino-IRremote 是驱动库，不是额外的设备码库。

## 安装与离线使用

### HACS 联网安装（推荐）

短暂让 HAOS 访问 GitHub，在 HACS 自定义存储库中添加
`https://github.com/MTJJ-z/ha-quanyu-zhilian`，类型选“集成”。
下载/更新“全域智联”到 `v0.3.0`，已装旧版可选择“重新下载”，完成后重启 HA。
HACS 会从 Release 下载 `quanyu_zhilian.zip`，包内已经包含完整数据库，
不需要在树莓派上执行脚本或再次下载码库。安装后可以恢复断网。

### 本地复制安装

将发布 ZIP 中的 `custom_components/quanyu_zhilian` 完整复制到 HA 的
`/config/custom_components/quanyu_zhilian`，保留 `data` 目录，重启 HA。
已配置全域智联网关时无需重新绑定。本次不需要为了码库更改 CYD 固件。
先在有网的电脑取得安装 ZIP，再通过本地文件传输带入 HAOS。

在 **开发者工具 → 操作** 执行：

```yaml
action: quanyu_zhilian.ir_search
data:
  query: TCL
  category: ACs
  limit: 20
  offset: 0
```

搜索操作需要返回响应。界面响应区域的 `profiles` 列出遥控器，`id` 是稳定的库内 ID。
`total` 为匹配总数，下一页增加 `offset`。分类是源库目录名，如 `ACs`、`TVs`、`Fans`。

```yaml
action: quanyu_zhilian.ir_inspect
data:
  profile_id: 从搜索结果复制id
```

`signals` 返回按键的 `index`、`name`、`format`、`protocol`、`cyd_sendable`、`limitation`。
同名按键以索引区分。不会因为名称相同覆盖记录。

```yaml
action: quanyu_zhilian.ir_send
data:
  gateway_id: cyd_08a570f3af48
  profile_id: 从搜索结果复制id
  signal_index: 0
```

发送先校验当前原型能力，再使用网关发现的 `ir.send_raw` 命令，等待执行回执。
不会自动重试。成功只说明发射动作完成，不能证明目标电器已改变状态。

## 当前发送边界

完整存储不等于全部可以发射。当前 CYD 0.2.1–0.3.0 的 raw 接口只支持：

- 2–100 段、每段 100–30000 微秒；
- 30–60 kHz 的整数 kHz 载波；
- 固定 50% 发射占空比。

其他记录保留在库中、可搜索查看，但发送时返回明确限制。
Flipper parsed 协议（NEC 等）需要额外编码适配，当前不会错误地把地址、命令字符串当作 raw 发出。
尤其空调通常发送完整状态帧，不能把 `TCL96AC` 协议名称当成设备型号或完整空调码库。
本次只交付本地库和原型 raw 调用入口；SD 同步、码库选择页面、完整空调 climate 模型尚未实现。

## 来源与许可

随包保留 `data/FLIPPER_IRDB_LICENSE` 和 `data/FLIPPER_IRDB_README.md`，
包括源项目的 CC0 声明及其“2319685 之前提交不在声明覆盖范围内”的说明。
不宣称旧贡献已全部获得新的 CC0 授权。原始文件中的注释、来源信息也保留。

## 可复现构建

在开发电脑取得完整仓库后：

```powershell
python build_ir_library.py G:\qyzl-v1\work\flipper-irdb
python build_release.py
```

构建脚本只读取指定本地仓库，记录 Git 提交、文件数、按键数、解析问题和数据库 SHA256，
不会自行下载或自动更新数据库。若未来增加导入源，应继续保留来源和适用许可。
