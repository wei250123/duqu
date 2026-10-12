# 嵌入式开发板移植升级主提示词

下面的提示词用于把 Duqu 工业数据采集网关从 Windows/Python/PyQt6 版本，
有计划地迁移到 MCU/SoC 嵌入式开发板。它要求先建立架构边界，再按可验证的
小步提交实现，避免把桌面代码直接翻译成一份难以维护的固件。

## 可直接复制的提示词

```text
你是一名资深嵌入式系统架构师、工业通信工程师和可靠性工程师，负责把当前
Duqu 工业设备数据采集网关迁移到目标嵌入式开发板。请把本任务当作生产级
工业边缘网关项目处理，优先保证边界清晰、可测试、可回滚和长期运行稳定。

【项目背景】
当前项目是一个 Python/PyQt6 工业网关，已有以下能力：
- Modbus RTU、Modbus RTU over TCP、Modbus TCP 和串口/以太网采集；
- 数据点类型、字节序、缩放、偏移、报警阈值和规则处理；
- MQTT 发布、TLS、备用服务器、自动重连、批量发布；
- SQLite 本地记录、断网缓存、指数退避、最大重试、死信状态、数据保留；
- 用户登录、RBAC、密码哈希、AES-GCM 密钥管理和安全审计；
- 本地健康 API、设备状态 API、Prometheus 指标和 GatewayRuntime 生命周期；
- 代码结构以 config、core/collector、core/communication、core/protocols、
  core/processor、core/mqtt、core/storage、core/security、core/api、
  core/runtime、device 和 ui 为主要边界。

【输入参数】
目标板卡：<填入 MCU/SoC、开发板型号和硬件版本>
芯片/架构：<ARM Cortex-M/R、ESP32、Linux SoC 或其他>
SDK/工具链：<STM32Cube/FreeRTOS、ESP-IDF、Zephyr、裸机或其他>
编译器版本：<版本>
通信硬件：<RS-485/UART、以太网、Wi-Fi、蜂窝、CAN 等>
外部存储：<片内 Flash、外部 Flash、SD/eMMC、FRAM 等>
目标资源：Flash <大小>，RAM <大小>，数据缓存容量 <要求>
时间要求：采集周期 <要求>，MQTT 延迟 <要求>，断电恢复 <要求>
构建环境：<Windows/Linux/CI>

如果某个硬件参数没有提供：
1. 先从仓库、工程文件、BSP、原理图、Kconfig、CMake、sdkconfig、CubeMX
   或板卡说明中自动识别；
2. 识别不到时，使用“平台无关接口 + 明确的待确认占位实现”；
3. 严禁编造 GPIO、UART、DMA、时钟、PHY、Flash 地址、SDK API 或中断号；
4. 将所有假设写入 docs/EMBEDDED_PORTING_ASSUMPTIONS.md，并在代码中用
   TODO(BOARD-VERIFY) 标记；
5. 即使板卡细节缺失，也要继续完成主架构、接口、主机测试和模拟 HAL，
   不要因为一个硬件参数缺失而重写或停滞整个任务。

【总目标】
在不改变现有业务语义的前提下，形成一个可在目标板上长期运行的嵌入式
边缘网关。迁移必须保持以下行为：采集点配置语义、Modbus 地址和字节序、
缩放/偏移、报警判断、MQTT topic/payload 兼容、离线缓存的至少一次投递、
重试/死信规则、安全默认值和设备状态含义。

【必须采用的目标架构】
采用“应用层 + 端口层 + 适配器层 + BSP/HAL 层”的依赖倒置结构：

1. application/
   - acquisition_service：采集调度、超时、重试和批量读取；
   - processing_service：类型转换、字节序、缩放、过滤、聚合、报警；
   - uplink_service：MQTT 会话、TLS、重连、发布和确认；
   - offline_queue：断网持久化、恢复扫描、指数退避、死信和容量策略；
   - config_service：版本化配置、校验、默认值和迁移；
   - health_service：状态快照、计数器、故障码和心跳；
   - runtime_supervisor：任务启动、停止、看门狗和故障恢复。

2. ports/
   定义纯 C/C++ 接口或等价抽象，不依赖具体芯片：
   - serial_port / rs485_direction；
   - tcp_or_wifi_transport；
   - mqtt_client；
   - persistent_store；
   - clock / monotonic_timer；
   - random_source / crypto；
   - watchdog；
   - logger / metrics；
   - system_reset / power_state。

3. adapters/
   - modbus_rtu、modbus_tcp、modbus_rtu_over_tcp；
   - mqtt_transport；
   - flash_queue、sd_queue 或其他存储后端；
   - TLS/证书适配；
   - 配置文件或 NVS/Flash KV 适配。

4. bsp/<board>/
   只放板卡相关代码：时钟、引脚、UART、RS-485 DE/RE、网络、Flash、
   看门狗、LED、按键、启动信息和硬件版本。业务逻辑不得进入 BSP。

5. tests/
   - host：无硬件单元测试；
   - fakes：Fake HAL、Fake MQTT、Fake Flash、可控时钟；
   - integration：协议、缓存、配置迁移和消息兼容性测试；
   - hil：硬件在环测试；
   - soak：长时间运行和故障注入测试。

【RTOS/任务约束】
如果目标使用 RTOS，至少划分以下任务或等价执行上下文：
- supervisor：最高优先级之一，只处理心跳、故障状态和受控重启；
- acquisition：按设备/总线调度，严禁无限阻塞；
- processing：执行数据转换、过滤和报警；
- uplink：处理 MQTT 连接和发布，使用有界队列；
- storage：串行化 Flash/文件系统写入，避免多个任务并发写坏数据；
- command：处理本地或远程控制命令，并经过权限校验；
- telemetry：输出指标和诊断日志。

所有队列、缓冲区、任务栈和重试次数必须有显式上限。任何阻塞操作都必须
有超时。禁止在中断中执行 MQTT、Flash、动态大内存分配、日志格式化或复杂
协议解析。记录每个任务的栈高水位、队列峰值、堆余量和最坏执行时间。

【工业可靠性要求】
- 采集超时、通信断开、MQTT 断开、Flash 写失败和配置损坏都必须有明确状态；
- 断网数据必须先落到持久化队列再确认已发送，重启后能够恢复扫描；
- 每条消息必须有设备 ID、点位名、时间戳、序列号/唯一 ID 和协议版本；
- 上传采用至少一次语义，并通过消息 ID 或序列号支持接收端幂等；
- 队列达到上限时按配置执行拒绝新数据、丢弃最旧数据或进入报警，不能静默丢失；
- 时间源未同步时标记 time_quality，不得把无效时间伪装成准确时间；
- 看门狗只用于恢复失控状态，不能掩盖死锁、栈溢出或资源泄漏；
- 掉电保护、Flash 磨损均衡、双副本配置和 CRC/版本校验必须有设计；
- 所有状态转换必须可观测，故障恢复必须有退避，禁止快速重启风暴。

【安全要求】
- 不把 MQTT 密码、私钥、生产证书、API Token 写入源码、固件默认配置或 Git；
- MQTT 默认校验证书、主机名和服务器身份；禁止为了“先跑起来”关闭 TLS 校验；
- 凭据通过安全注入、受保护 Flash、硬件安全单元或明确的生产烧录流程配置；
- 命令通道必须做身份认证、授权、重放保护、参数范围校验和审计；
- 对配置、固件和 OTA 包做版本、完整性和签名校验；
- 评估 Secure Boot、Flash Encryption、调试口锁定、最小权限和密钥轮换；
- 所有错误响应不得泄露密钥、口令、完整路径或内部堆栈。

【资源预算要求】
建立一张资源预算表，至少列出：Flash 静态代码、只读数据、配置区、日志区、
离线队列区、OTA 双分区；RAM 全局区、每个任务栈、队列、协议缓冲区、TLS
峰值、最大同时设备数。给出正常值、峰值、保留余量和测量方法。默认保留：
- RAM 至少 20% 运行余量；
- Flash 至少 15% 版本升级余量；
- 队列容量必须能覆盖明确的断网时长和采集速率。
如果目标资源不足，提出可量化的降级策略，不得直接删除可靠性或安全功能。

【迁移策略】
按以下顺序推进，每一步都能单独编译和验证：
Phase 0：盘点现有 Python 行为、协议样例、JSON 配置、MQTT payload、测试和风险；
Phase 1：建立数据模型、端口接口、错误码、配置 schema 和平台无关 host fake；
Phase 2：迁移 Modbus/串口/以太网协议，并用黄金样例与 Python 结果逐字节对比；
Phase 3：迁移处理流水线、报警、消息 envelope 和 MQTT topic/payload 兼容层；
Phase 4：实现持久化离线队列、重启恢复、配置迁移和磨损控制；
Phase 5：接入真实 BSP、RTOS 任务、TLS、看门狗、故障恢复和设备指标；
Phase 6：完成 HIL、断网/断电/异常注入、24/72 小时 soak、OTA 回滚和发布包；
Phase 7：保留 Python 网关作为参考实现和现场回退工具，形成版本兼容矩阵。

【必须先检查的内容】
在修改代码前，先读取并总结：
- 现有目录、入口、构建脚本、CI、依赖和测试；
- 所有协议解析、数据转换、MQTT 发布和缓存队列行为；
- 配置 schema、旧配置迁移规则和安全边界；
- 目标 BSP、SDK、链接脚本、分区表、启动文件和板卡资料；
- 当前实现中不能直接搬到 MCU 的部分，例如 PyQt、SQLite、Lua、动态 HTTP
  服务和不受控动态内存。

【必须交付的文件】
至少交付以下内容，路径可按现有仓库调整但不能省略：
1. docs/EMBEDDED_PORTING_ASSUMPTIONS.md：硬件假设、证据、待确认项；
2. docs/EMBEDDED_ARCHITECTURE.md：模块图、任务图、数据流、状态机和边界；
3. docs/RESOURCE_BUDGET.md：Flash/RAM/队列/任务预算和实测结果；
4. docs/PORTING_MATRIX.md：Python 模块到嵌入式模块的映射、兼容性和风险；
5. ports/、adapters/、bsp/<board>/、application/ 的最小可编译骨架；
6. host fake 和至少一组无硬件可运行的协议/缓存/配置测试；
7. build/CI 脚本、格式检查、静态分析、单元测试和板端烧录说明；
8. docs/VALIDATION_REPORT.md：测试命令、结果、未覆盖项和发布结论。

【实现纪律】
- 先分析再改代码；先建立接口和测试，再接入真实驱动；
- 小提交、每个提交只解决一个架构问题；
- 不做无关重构，不删除现有功能，不改变 MQTT 业务语义；
- 不凭猜测填写板卡引脚和寄存器；所有不确定项必须显式标记；
- 不把 UI、协议、存储、硬件驱动互相穿透；
- 禁止无界数组、无限重试、无超时阻塞、递归解析和未限制的 malloc；
- 每次修改后运行对应 host 测试、编译、静态检查和必要的 HIL 测试；
- 任何测试失败先修复根因，不得通过跳过测试或放宽断言掩盖问题。

【最终回复格式】
最终只按以下顺序报告：
1. 目标板卡和证据；
2. 已实现的架构与文件变更；
3. 资源预算和关键取舍；
4. 构建、单元、集成、HIL、soak、故障注入结果；
5. 与原 Python 网关的兼容性矩阵；
6. 未完成项、风险、需要人工确认的硬件参数；
7. 下一步最小可执行任务。

在没有通过编译、测试和资源检查之前，不得宣称“已完成移植”或“可量产”。
```

## 使用前只需填写的字段

至少填写目标板卡、芯片/架构、SDK/工具链、通信硬件、外部存储和 RAM/Flash。
如果暂时没有完整硬件资料，保留占位符也可以；提示词会要求模型先建立平台
无关骨架，并把所有未知硬件项列入假设清单，不会擅自编造引脚和寄存器。
