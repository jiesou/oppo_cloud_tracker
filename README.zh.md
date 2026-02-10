# OPPO Cloud HeyTap Tracker

使用 [OPPO (欢太) 云服务](https://cloud.oppo.com)的查找手机功能来定位 OPPO/OnePlus 设备，并将其集成到 Home Assistant 作为设备追踪器实体。

<img width="560" alt="ha device" src="https://github.com/user-attachments/assets/5b8dda5c-f751-4f9a-b184-27affb0f72d5" />
<img width="560" alt="device tracker" src="https://github.com/user-attachments/assets/db90e6ea-19fd-416e-9c64-4d0439ff036d" />

## 功能

可以提供这些信息：

- **设备型号**
- **位置名称**
- **GPS 经纬度**
- **最后更新时间**
- **在线状态**
- *可能、也许、大概* 支持多台设备， **我没有测试条件**

## 预先要求

集成是通过 Playwright（类 Selenium）实现的，只支持手机号和密码登录。同时：
**警告：密码存储的安全性不受保证**

它需要一个**独立的支持 CDP 的远程浏览器后端，例如 [Browserless](https://github.com/browserless/browserless)**，或者也支持 [Selenium Grid](https://www.selenium.dev/zh-cn/documentation/grid) 实例

如果没有合适的机子来跑 Browserless，也可以考虑一些部署在云上的方案，选择也有很多

### 远程浏览器后端设置

#### 方案一：Playwright + CDP
推荐直接用 Docker browserless/chromium 镜像来部署 Playwright + CDP 浏览器后端

参考 `docker-compose.yml`：
```yaml
name: browserless
services:
  browserless-chrome:
    container_name: browserless-chrome
    image: ghcr.io/browserless/chromium:latest
    environment:
      - CONCURRENT=3
      - TIMEOUT=600000
      - TOKEN=[TOKEN(changeme)]
    ports:
      - target: 3000
        published: "3000"
        protocol: tcp
    restart: unless-stopped
```

然后你就能得到你的“浏览器后端地址”，形似
`ws://[your_docker_hostname]:3000/chromium/playwright?token=[TOKEN(changeme)]`
请确保 Home Assistant 实例能够访问到 Docker 容器

如果不需要 Browserless 的复杂功能，普通的 playwright/chrome 镜像当然也应该能正常工作

#### 方案二：Selenium Grid

可以使用经典传统 Selenium Grid API 的方案。但不建议使用。
这个实现基于 [Playwright 的支持](https://playwright.dev/python/docs/selenium-grid)。因为 Selenium 不如 Playwright + CDP 来得可靠，性能和效率都更差一些。

推荐使用 Docker selenium/standalone-chrome 镜像来部署 Selenium Grid。

参考 `docker-compose.yml`：
```yaml
name: selenium
services:
  standalone-chrome:
    container_name: selenium-chrome
    image: selenium/standalone-chrome:latest
    shm_size: 2gb
    environment:
      # 外部会通过 SE_NODE_GRID_URL 来访问 standalone-chrome，如果设置了网络映射那这便是必要的
      -  SE_NODE_GRID_URL=http://[your_docker_hostname]:4444
    ports:
      - target: 4444
        published: "4444"
        protocol: tcp
      - target: 7900
        published: "7900"
        protocol: tcp
    restart: unless-stopped
```

然后你就能得到你的“浏览器后端地址”，形似
`http://[your_docker_hostname]:4444/wd/hub`
请确保 Home Assistant 实例能够访问到 Docker 容器

## 安装

### 方法 1：HACS（推荐）

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

### 方法 2：手动安装

1. 下载存储库
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

- **浏览器后端地址**：您的浏览器后端实例的 URL
  - 对于 Browserless：`ws://[your_docker_hostname]:3000/chromium/playwright?token=[TOKEN(changeme)]`
  - 对于 Selenium Grid：`http://[your_docker_hostname]:4444/wd/hub`
  - 请确保 Home Assistant 实例能够访问到 Docker 容器
- **OPPO 手机号**：您的 OPPO 账户手机号（仅支持 +86）
- **OPPO 密码**：您的 OPPO 账户密码， **再次警告：密码安全性不受保证**

设置完集成后，还可以配置扫描间隔，默认 300 秒（5 分钟）更新一次

集成会创建一个名为 "保持浏览器会话" 的虚拟开关来控制会话行为：

- **开启**：在更新之间保持浏览器会话活跃
  - 允许更高的刷新频率
  - 需要设备持续报告 GPS（高电池消耗）
  - 更适合实时追踪

- **关闭**（默认）：每次更新后关闭浏览器会话
  - 每次更新都会重启浏览器并重新登录 OPPO 云服务
  - 对设备电池影响较小
  - 适合定期位置检查

它还能提供一个 `oppo_cloud_tracker.locate` Service 用来在自动化脚本中手动触发设备位置的立即更新

## FAQ

1. **无法连接到浏览器后端**
   - 验证浏览器后端 URL 是否正确
   - 对于 Selenium Grid，检查 SE_NODE_GRID_URL 是否配置正确。确保 Home Assistant 能够访问它： **SE_NODE_GRID_URL 应该设置为外部的端口、主机名**
   - 确保 Home Assistant 能够访问 Docker 容器
   - 检查容器是否正在运行

2. **OPPO 登录失败**
   - 验证您的手机号和密码是否正确
   - 仅支持 +86（中国）手机号
   - 先尝试手动登录 OPPO 云服务网站

3. **Selenium Grid: session not created from unknown error: cannot create default profile directory**
   - 你需要在 docker-compose.yaml 中添加 shm_size: 2gb，参考 [SeleniumHQ/docker-selenium](https://github.com/SeleniumHQ/docker-selenium#--shm-size2g)
   - 检查是否磁盘空间已经不足了

4. **奇怪的错误或超时**
   - 由于通过 Playwright 操作，集成初始化、fetching 的动作一般要花费十几秒钟，比一般集成更费时间是正常的。建议为 Browserless 容器设置 60s 的 TIMEOUT
   - 但如果花费的时间经常超过 30 秒，那最好检查、重启一下 Browserless
   - 重启 Browserless Docker 容器：
     ```bash
     docker restart browserless-chrome
     ```
   - 检查 Browserless Docker 日志：
     ```bash
     docker logs browserless-chrome
     ```

### Tips & Tricks

- Selenium Grid 网页提供 VNC 查看器：http://[your_docker_hostname]:7900
- Home Assistant 日志将在 `custom_components.oppo_cloud_tracker` 下显示集成活动

## 免责声明

本集成与 OPPO 无关且未获得 OPPO 认可。它基于公开可用的网页界面，所有对网页的动作都遵循用户的配置。如果 OPPO 更改其网站，可能会停止工作。使用风险自负。
