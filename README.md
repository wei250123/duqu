# 工业设备数据采集与 MQTT 上传网关

基于 PyQt6 的工业设备数据采集桌面网关：通过 Modbus RTU/TCP 和串口采集设备寄存器数据，处理后按规则上传至 MQTT 服务器。

## 功能特性

- **多协议采集**：Modbus RTU / Modbus RTU over TCP / Modbus TCP，支持串口（COM）与以太网连接，自动重连
- **数据点配置**：寄存器地址、数据类型（float32/uint32 等）、字节序、缩放/偏移、高低报警阈值
- **MQTT 上传**：批量发布、上传速率限制、备份服务器、数据过滤
- **数据处理**：Lua 脚本插件扩展（lupa）、数据缓存与断网续传
- **可视化**：matplotlib 实时曲线、历史数据导出（CSV）
- **安全**：启动登录、角色权限（admin / operator / viewer）、持久化账户、密码哈希、AES-GCM 数据加密、可选启动密码
- **运维**：看门狗、分级日志、配置热加载

## 环境要求

- Python 3.10+
- Windows（串口设备）

## 安装运行

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 开发/测试环境
pip install -r requirements-dev.txt

# 运行测试
python -m pytest -q

# 启动
python main.py
```

## 默认账户

| 角色 | 用户名 | 初始密码 |
|------|--------|----------|
| 管理员 | admin | admin123 |
| 操作员 | operator | operator123 |
| 观察者 | viewer | viewer123 |

> 上线前请务必修改默认密码。

程序启动时必须登录。账户保存在 `data/config/users.json`，新增用户和密码修改会原子写入；普通操作员不能修改设备配置，观察者不能执行设备控制或调试操作。

启动密码会以哈希形式保存。旧版本明文启动密码只会在成功验证后自动迁移，之后不会继续写回明文。

启用数据加密后，程序使用 AES-GCM。默认会在 `data/config/encryption.key` 生成随机密钥；生产环境可通过 `IIOT_GATEWAY_ENCRYPTION_KEY` 注入 Base64 编码的 16、24 或 32 字节密钥。密钥文件和运行时数据不要提交到 Git。

## 项目结构

```
├── main.py              # 程序入口
├── config/              # 配置管理
├── core/
│   ├── collector/       # 采集引擎
│   ├── communication/   # 串口/网络通信
│   ├── protocols/       # Modbus 等协议解析
│   ├── processor/       # 数据处理
│   ├── mqtt/            # MQTT 客户端
│   ├── security/        # 认证与加密
│   └── storage/         # 缓存与数据库
├── device/              # 设备管理器
├── plugins/             # Lua 插件基类
├── ui/                  # PyQt6 界面（页面/组件）
└── utils/               # 日志、看门狗、工具
```

## 说明

- `json/` 目录下的点位配置为示例数据，可按实际设备修改
- 运行时数据（数据库、日志、设备配置）生成于 `data/` 目录，已加入 `.gitignore`

## License

MIT
