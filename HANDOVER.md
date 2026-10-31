# CampusHub Sync (CampusHub Android) 工程架构与开发交接文档

> **当前正式版本**：`v2.3.6` (VersionCode: 38)  
> **开源仓库**：`https://github.com/NoraNekowww/campushub-sync`  
> **生产服务域名**：`https://nzlab.online/schedule/` (公网直连 IP: `108.186.202.38`，套 Cloudflare CDN)  
> **APK 生产分发直链**：`https://nzlab.online/schedule/CampusHub.apk`  
> **交接日期**：2026-10-31

---

## 一、系统全景架构与运行环境

本项目为面向大学生的课表、个人日程、多源待办同步管理系统，包含 **FastAPI 后端**、**Vue 3 前端 (SPA/PWA)** 以及 **Android 原生离线 WebView 客户端**。

```
                       ┌─────────────────────────┐
                       │  CampusHub Android App  │
                       │   (Java + WebView)      │
                       └────────────┬────────────┘
                                    │ WebViewAssetLoader
                       ┌────────────▼────────────┐
                       │   Vue 3 SPA (本地离线)   │
                       │   https://appassets...  │
                       └────────────┬────────────┘
                                    │ HTTPS (Cookie + X-Session-Token)
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│       Cloudflare CDN         │              │    天大官方统一身份认证 CAS    │
│  (https://nzlab.online/...)  │              │    sso.tju.edu.cn            │
└──────────────┬───────────────┘              │    classes.tju.edu.cn/eams   │
               │                              └──────────────▲───────────────┘
┌──────────────▼───────────────┐                             │
│   VPS 生产服务器 (Ubuntu)     │                             │
│   FastAPI (campushub-sync)   │─────────────────────────────┘
│   /var/www/schedule/...      │  (主路径全自动 OCR 爬虫直连导入课表)
└──────────────────────────────┘
```

### 1. 核心运行环境与目录规范
- **本地工作区**：`E:\Alpha_nz_Files\campushub-sync`
  - 前端源码：`web/`
  - Android 工程：`android/`
  - 后端服务：`backend/`
  - 工具链配置：
    - `JAVA_HOME`: `E:\Alpha_nz_Files\_toolchain\jdk`
    - `ANDROID_HOME`: `E:\Alpha_nz_Files\_toolchain\android-sdk`
    - `Gradle`: `E:\Alpha_nz_Files\_toolchain\gradle-8.7\bin\gradle.bat`
- **生产服务器 (VPS)**：
  - 公网直连 IP：`108.186.202.38`（**注意**：SSH/SCP 连接必须直连 IP，因域名套了 Cloudflare CDN 会被拦截 22 端口超时）
  - 前端生产静态路径：`/var/www/schedule/frontend/`
  - 后端代码路径：`/var/www/schedule/backend/app/`
  - systemd 服务名：`campushub-sync`
  - SSH 私钥路径：`C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa`

---

## 二、关键业务模块与技术规范

### 1. 天大课表导入机制（v2.3.6 已彻底纯粹化）
- **唯一主路径**：全面收敛至官方教务 CAS（`sso.tju.edu.cn` 统一身份认证直通 `classes.tju.edu.cn/eams`）。
- **去繁就简**：已彻底剔除微北洋浏览器直连、CORS 伪造、手动粘贴 JSON、本地微北洋 Token 存储、ICS 文件上传等各种历史无效兜底。
- **免校园网限制**：服务器公网直连教务，自带内置 OCR 识别图形验证码；仅在自动识别未通过时提示手填一次 4 位验证码。
- **作息与学期规则**：
  - 天大标准作息：白天 1-8 节 08:30 起；9-10 节连上 18:30-20:00 无课间（11-12 节顺延）；
  - 节数严禁按 `时长/45` 估算，必须使用 `EventOut.periods=[起, 止]`；
  - 教务周次位图第 1 位为报到周，真实教学周 = `位次 - 1`。

### 2. 双端离线秒开架构与会话管理
- **Android 本地化拦截**：
  - 基于 Google 官方 `WebViewAssetLoader` 将 `assets/web/` 映射至安全虚拟域 `https://appassets.androidplatform.net/schedule/`；
  - 零网络依赖开屏即开，支持离线 LocalStorage 与现代 Web API。
- **API 基地址与双通道鉴权**：
  - `web/src/api.js` 中 `detectBase()` 自动识别虚拟域，将 API 强制重定向至远程 `https://nzlab.online/schedule/api`；
  - 采用 **Cookie + `X-Session-Token` 请求头** 双通道会话机制，彻底规避跨域环境下 Cookie 被浏览器安全策略丢弃的问题；
  - 取消了所有历史 `ADMIN_TOKEN` 访问令牌概念，全局统一收敛为成熟的账号注册/登录体系。
- **防开屏闪烁（0ms 状态直出）**：
  - 在 `web/src/store.js` 顶层通过 `readInitialUser()` 和 `readInitialEvents()` 同步还原闪存，时差归零，杜绝挂载时短暂弹出登录门的闪烁。

### 3. 数据同步与并发安全（防左右脑互搏）
- **持久化删除墓碑机制（Tombstone）**：
  - 键名：`campushub.deleted_event_ids.v1`；
  - 无论在日程列表还是周课表删除任务，立即打入本地墓碑；
  - 后台静默 `refresh()`、离线同步回写、周课表重载均强制经过墓碑过滤，**彻底终结了删除任务后 2 秒内被旧缓存冲刷复活的并发 Bug**；
  - 用户点击撤销（Undo）时，通过 `unrecordDeletedEventId` 安全解封。
- **本地零延迟响应式联动**：
  - 周课表（`WeekView.vue`）深度监听 `state.events`，在左侧线性表增删改或划掉待办时，周课表毫秒级响应重绘。

### 4. 课表交互与 UI 视觉规范
- **顶栏控件严格等高**：
  - 搜索按钮、同步按钮（带加载旋转动效）、设置按钮统一设定为 `!h-9`（36px）绝对等高对齐。
- **课表底色三态切换**：
  - **标准网格**（默认）：整点水平轻量参考标线；
  - **细分网格**：在整点基础上每半小时（`XX:30`）补充点状参考虚线，对齐课程起止更精准；
  - **极简空白底**：隐藏内部水平线，视觉通透；
  - 偏好自动持久化在本地 `campushub.week_grid_style` 中。
- **DDL 精准定位与呼吸轮换机制**：
  - DDL 严格按具体截止分钟数映射在垂直时间轴百分比坐标；
  - 当出现「DDL 与课程重叠」或「多个 DDL 时间重叠」时，自动划入冲突轮换组；
  - 组内各项目以 4s 为周期依次轮流呼吸亮灭（`opacity: 1` 提升 z-index，未轮到时 `opacity: 0.28`），消灭视觉遮挡。
- **历史归档设计**：
  - 全量展示所有已完结个人日程与待办（排除天大自带课程）；
  - 严格按日期从近到远（时间倒序上下排列）：最上方即为刚刚完成的任务，支持大圆复选框一键复原。

---

## 三、标准化构建与发布流程

后续任何迭代开发，请严格遵循以下发布操作流水线：

### 步骤 1：前端编译与资源注入
```bash
# 1. 编译 Web 生产产物
cd "E:/Alpha_nz_Files/campushub-sync/web"
VITE_BASE=/schedule/ npm run build

# 2. 覆盖同步至 Android assets 目录
cd "E:/Alpha_nz_Files/campushub-sync"
rm -rf android/app/src/main/assets/web/assets
cp -r web/dist/assets android/app/src/main/assets/web/
cp web/dist/index.html android/app/src/main/assets/web/
cp web/dist/sw.js android/app/src/main/assets/web/
```

### 步骤 2：Android 原生 APK 打包
```powershell
# 在 PowerShell 中调用配置好的免安装工具链
$ToolRoot = 'E:\Alpha_nz_Files\_toolchain'
$env:JAVA_HOME        = "$ToolRoot\jdk"
$env:ANDROID_HOME     = "$ToolRoot\android-sdk"
$env:ANDROID_SDK_ROOT = "$ToolRoot\android-sdk"
$env:PATH             = "$ToolRoot\jdk\bin;$ToolRoot\android-sdk\platform-tools;$env:PATH"
$env:JAVA_TOOL_OPTIONS = '-Duser.language=en -Duser.country=US -Dfile.encoding=UTF-8'

cd E:\Alpha_nz_Files\campushub-sync\android
& "$ToolRoot\gradle-8.7\bin\gradle.bat" --console=plain --no-daemon assembleRelease
```
打包成功后，将生成的 `app-release.apk` 复制覆盖至工作区根目录及前端静态发布目录：
```bash
cp E:/Alpha_nz_Files/campushub-sync/android/app/build/outputs/apk/release/app-release.apk E:/Alpha_nz_Files/campushub-sync/CampusHub.apk
cp E:/Alpha_nz_Files/campushub-sync/android/app/build/outputs/apk/release/app-release.apk E:/Alpha_nz_Files/campushub-sync/web/dist/CampusHub.apk
```

### 步骤 3：部署更新至线上 VPS
```bash
# 1. SCP 上传后端核心文件
scp -i "C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa" \
  E:/Alpha_nz_Files/campushub-sync/backend/app/main.py \
  root@108.186.202.38:/var/www/schedule/backend/app/
scp -i "C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa" \
  E:/Alpha_nz_Files/campushub-sync/backend/app/api/status.py \
  root@108.186.202.38:/var/www/schedule/backend/app/api/

# 2. 打包前端静态包并管道传输解压（防跨国网络 reset）
cd "E:/Alpha_nz_Files/campushub-sync/web/dist"
tar --exclude="*.apk" -czf ../frontend_latest.tar.gz .
cat ../frontend_latest.tar.gz | ssh -i "C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa" root@108.186.202.38 "tar -xzf - -C /var/www/schedule/frontend/"

# 3. 重启后端服务守护进程
ssh -i "C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa" root@108.186.202.38 "systemctl restart campushub-sync && systemctl is-active campushub-sync"
```

### 步骤 4：GitHub 提交与发版 (Release)
```bash
cd "E:/Alpha_nz_Files/campushub-sync"
git add -A
git commit -m "feat: release vx.y.z ..."
git push origin main

# 创建 Release 并挂载 APK 资产
gh release create vx.y.z ./CampusHub.apk --title "CampusHub Android vx.y.z" --notes "..."

# 同步服务器上的直链下载包
ssh -i "C:/Users/NorazA/Desktop/AboutServer/.ssh/.ssh/id_rsa" root@108.186.202.38 \
  "curl -s -L -A 'Mozilla/5.0' -o /var/www/schedule/frontend/CampusHub.apk https://github.com/NoraNekowww/campushub-sync/releases/download/vx.y.z/CampusHub.apk && chmod 644 /var/www/schedule/frontend/CampusHub.apk"
```

---

## 四、交接文件索引与后续工程建议

| 文件相对路径 | 模块职责 | 维护注意事项 |
|---|---|---|
| `web/src/components/AppHeader.vue` | 顶栏导航、搜索展开、同步触发、设置入口 | 维持按钮 `!h-9` 严格等高约束 |
| `web/src/components/TjuConnect.vue` | 天大教务一键 CAS 登录导入面板 | 严禁复活微北洋/手动粘贴等陈旧兜底代码 |
| `web/src/views/WeekView.vue` | 课表视图、网格渲染、DDL 定位与呼吸算法 | 联动同步严禁盲目逆向回写已被墓碑标记的事件 |
| `web/src/views/HistoryView.vue` | 历史归档列表 | 保持全量倒序上下排列，卡片不带删除按钮 |
| `web/src/views/SettingsView.vue` | 外观底色切换、账户管理、小部件引导 | 版本号动态读取 Android 注入的原生版本 |
| `web/src/store.js` | 状态存储、删除墓碑（Tombstone）、离线队列 | 涉及修改/删除逻辑均需经由墓碑校验 |
| `backend/app/api/tju.py` | 后端教务 CAS 爬取逻辑 | 定期维护验证码识别模型与教务 Session 存活 |
| `android/app/src/main/java/.../MainActivity.java` | Android 容器、离线资产拦截器、JS 桥梁 | 确保 `NativeAuthBridge` 提供 `getAppVersion()` |

---
*文档已写入工作区根目录 `HANDOVER.md`，可随时查阅复用。*
