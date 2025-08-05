# OPPO Cloud HeyTap 设备追踪器

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

使用 OPPO (HeyTap) 云服务的查找手机功能来定位 OPPO/OnePlus 设备，并将其集成到 Home Assistant 作为设备追踪器实体。

[简体中文文档](README.zh.md) | [English Documentation](README.md)

## ⚠️ 安全警告

**本集成使用手机号和密码进行身份验证，密码安全性无法得到保证！** 本集成通过 Selenium WebDriver 自动化 OPPO 云服务网页界面，这意味着您的凭据将被浏览器自动化程序处理。请自行承担风险，如有可能建议使用专用账户。

## 功能特性

本集成为您的 OPPO/OnePlus 设备提供以下信息：

- **设备型号** - 您设备的型号名称
- **位置名称** - 设备位置的人类可读地址
- **GPS 坐标** - 纬度和经度数据
- **电池电量** - 当前电池百分比
- **最后更新时间** - 设备最后一次报告位置的时间
- **在线状态** - 设备当前是否在线
- **多设备支持** - 可能支持多台设备（作者未测试）

## 系统要求

本集成需要一个**独立的 Selenium Grid 实例**才能运行。由于没有官方 API，它使用 Selenium WebDriver 来自动化 OPPO 云服务网页界面。

### Selenium Grid 设置

推荐使用 Docker 和 `selenium/standalone-chrome` 镜像来部署 Selenium Grid。

创建 `docker-compose.yml` 文件：

```yaml
name: selenium
services:
  standalone-chrome:
    cpu_shares: 90
    command: []
    container_name: selenium-chrome
    hostname: selenium-chrome
    image: selenium/standalone-chrome:latest
    ports:
      - target: 4444
        published: "4444"
        protocol: tcp
      - target: 7900
        published: "7900"
        protocol: tcp
    restart: unless-stopped
    network_mode: bridge
    privileged: false
```

然后运行：
```bash
docker-compose up -d
```

有关 Selenium Grid 的更多信息，请访问：https://www.selenium.dev/zh-cn/documentation/grid/

## 安装方法

### 方法 1：HACS（推荐）

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

1. 点击上方徽章或手动将此存储库添加到 HACS
2. 搜索 "OPPO Cloud HeyTap Tracker"
3. 安装集成
4. 重启 Home Assistant

### 方法 2：手动安装

1. 下载此存储库
2. 将 `custom_components/oppo_cloud_tracker` 文件夹复制到您的 Home Assistant 的 `custom_components` 目录
3. 重启 Home Assistant

## 配置

### 第一步：添加集成

1. 转到 **设置** → **设备与服务**
2. 点击 **添加集成**
3. 搜索 "OPPO Cloud HeyTap Tracker"
4. 点击添加集成

### 第二步：配置连接

您需要提供：

- **Selenium Grid URL**：您的 Selenium Grid 实例的 URL
  - 格式：`http://[your_docker_hostname]:4444/wd/hub`
  - 默认：`http://localhost:4444/wd/hub`
  - 确保您的 Home Assistant 实例能够访问 Docker 容器
- **OPPO 手机号**：您的 OPPO 账户手机号（仅支持 +86）
- **OPPO 密码**：您的 OPPO 账户密码

### 第三步：配置选项（可选）

添加集成后，您可以配置其他选项：

- **扫描间隔**：更新设备位置的频率（默认：300 秒 / 5 分钟）
  - 范围：30-3600 秒
  - ⚠️ **注意电池消耗！** 较短的间隔需要设备更频繁地报告 GPS

### 第四步：会话管理

集成会创建一个名为 "Keep Selenium Session" 的虚拟开关来控制会话行为：

- **开启**：在更新之间保持 Selenium 会话活跃
  - 允许更高的刷新频率
  - 需要设备持续报告 GPS（高电池消耗）
  - 更适合实时追踪
  
- **关闭**（默认）：每次更新后关闭 Selenium 会话
  - 每次更新都会重启 Selenium 并重新登录 OPPO 云服务
  - 对设备电池影响较小
  - 适合定期位置检查

## 使用方法

配置完成后，集成将：

1. 为每个发现的 OPPO/OnePlus 设备创建设备追踪器实体
2. 根据您配置的扫描间隔更新设备位置
3. 将设备信息作为实体属性提供
4. 通过 "Locate Devices" 服务允许手动位置更新

### 可用服务

- **定位设备** (`oppo_cloud_tracker.locate`)：触发所有设备位置的立即更新

## 故障排除

### 常见问题

1. **无法连接到 Selenium Grid**
   - 验证 Selenium Grid URL 是否正确
   - 确保 Home Assistant 能够访问 Docker 容器
   - 检查 Selenium Grid 容器是否正在运行

2. **OPPO 登录失败**
   - 验证您的手机号和密码是否正确
   - 仅支持 +86（中国）手机号
   - 先尝试手动登录 OPPO 云服务网站

3. **设备未出现**
   - 确保设备已链接到您的 OPPO 账户
   - 检查设备位置服务是否已启用
   - 等待初始扫描完成

4. **奇怪的错误或超时**
   - 重启 Selenium Grid Docker 容器：
     ```bash
     docker restart selenium-chrome
     ```
   - 检查 Selenium Grid 日志：
     ```bash
     docker logs selenium-chrome
     ```

### 调试信息

- Selenium Grid 网页界面：http://[your_docker_hostname]:7900（VNC 查看器）
- Home Assistant 日志将在 `custom_components.oppo_cloud_tracker` 下显示集成活动

## 限制

- 仅支持手机号 + 密码身份验证
- 仅支持 +86（中国）手机号
- 需要 Home Assistant 和被追踪设备都有活跃的互联网连接
- 无法保证密码安全性（浏览器自动化）
- 多设备支持未经测试
- 可能受 OPPO 云服务网站变更影响

## 贡献

欢迎贡献！请随时提交问题、功能请求或拉取请求。

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 免责声明

本集成与 OPPO 无关且未获得 OPPO 认可。它使用公开可用的网页界面，如果 OPPO 更改其网站，可能会停止工作。使用风险自负。