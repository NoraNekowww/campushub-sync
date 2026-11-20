# CampusHub Sync — Agent 交接手册

> **给接手开发的同学 / Agent**：这份文档是唯一入口。读完最后一节「红线与已知坑」再动手。
>
> | 项 | 值 |
> |---|---|
> | 当前版本 | `v2.9.3`（Android `versionCode 95`，`sw.js` `campushub-v95`） |
> | 下一版 | `v2.9.4`（versionCode `96`） |
> | 生产地址 | `https://nzlab.online/schedule/` |
> | APK 直链 | `https://nzlab.online/schedule/CampusHub.apk` |
> | 源码仓库 | `https://github.com/NoraNekowww/campushub-sync`（分支 `main`） |
> | 本地工作区 | `E:\Agent_Workspace_Isolated\campussync` |
> | VPS | `root@108.186.202.38`（**必须直连 IP**，域名套了 Cloudflare，22 端口会超时） |
> | 交接日期 | 2026-11-17 |

---

## 0. 先跑起来：三条命令确认环境

```bash
cd E:/Agent_Workspace_Isolated/campussync
git status                       # 应当干净
git log --oneline -3             # d0fb803 fix: rebuild web assets with schedule base path
curl -s https://nzlab.online/schedule/api/version   # 应当返回 "version":"2.9.0"
```

三样都通 → 环境正确，可以开工。任一不通 → 见文末「红线与已知坑」。

---

## 1. 这是什么

面向大学生的**课表 + 日程 + 待办聚合系统**，一套数据三种前端：

```
          ┌───────────────────────────┐
          │ Android APK（Java + WebView）│  离线开屏，assets/web/ 内嵌同一份前端
          └─────────────┬─────────────┘
                        │ WebViewAssetLoader → https://appassets.androidplatform.net/schedule/
          ┌─────────────▼─────────────┐
          │  Vue 3 SPA / PWA（同一套码）│  https://nzlab.online/schedule/
          └─────────────┬─────────────┘
                        │ HTTPS，Cookie + X-Session-Token 双通道鉴权
          ┌─────────────▼─────────────┐        ┌──────────────────────────┐
          │ FastAPI (uvicorn :8010)    │───────▶│ 天大 SSO CAS + eams 教务  │
          │ /var/www/schedule/backend  │        │ sso/classes.tju.edu.cn   │
          └─────────────┬─────────────┘        └──────────────────────────┘
                        │
              SQLite /var/www/schedule/data/campushub.db
```

**前端只有一份**：`web/`。网页端和 APK 用的是同一套构建产物，只是 APK 把 `web/dist/` 拷进 `android/app/src/main/assets/web/` 里离线打包。所以**改 UI 只需改 `web/`，然后两边各自发布一次**。

技术栈：Vue 3 + Vite 5 + Tailwind（前端）、FastAPI + SQLModel + SQLite（后端）、Java + WebViewAssetLoader（Android）、nginx（反代 + 静态）、systemd（守护）。

---

## 2. 目录结构（只列要动的）

```
campussync/
├─ web/                          ← 前端全部源码，改 UI 只改这里
│  ├─ src/
│  │  ├─ api.js                  API 基址探测 + 离线白名单 + 所有请求方法
│  │  ├─ store.js                全局状态（最大单体文件，改动前必读）
│  │  ├─ App.vue                 路由/视图切换（无 vue-router，state.view 手写）
│  │  ├─ views/
│  │  │  ├─ AgendaView.vue       线性日程列表（DDL/日程/含课表/历史归档 四个筛选）
│  │  │  ├─ WeekView.vue         周课表，网格 + DDL 垂直定位 + 冲突呼吸轮换
│  │  │  ├─ TodoView.vue         「可办事项」页（无截止待办）
│  │  │  └─ SettingsView.vue     外观/账号/小部件
│  │  ├─ components/
│  │  │  ├─ AppHeader.vue        顶栏：标题（含计数）、搜索、同步、设置
│  │  │  ├─ EventEditor.vue      日程/待办编辑器（最大的表单组件）
│  │  │  ├─ EventCard.vue        列表卡片，左滑删除 / 右滑星标
│  │  │  ├─ TjuConnect.vue       教务一键导入（在线 / 离线两套分支）
│  │  │  ├─ TodoQuickAdd.vue     可办事项极简弹层（标题+备注）
│  │  │  ├─ FilterBar.vue        日程栏筛选胶囊
│  │  │  └─ AuthGate.vue         登录 / 注册 / 离线模式入口
│  │  ├─ utils/
│  │  │  ├─ dedupe.js            课程内容去重（两套 event id 体系的收口）
│  │  │  ├─ parseScheduleText.js 自然语言识别（「明天下午三点开会」）
│  │  │  ├─ datetime.js          时间工具（时间轴用）
│  │  │  ├─ themeColors.js       主题色板（莫兰迪系）
│  │  │  └─ wallpapers.js        背景图配置
│  │  └─ composables/            手势 / 长按等复用逻辑
│  ├─ public/                    sw.js、manifest、icons、widget.html
│  └─ scripts/                   test_parse.mjs（55 例）、test_dedupe.mjs（10 例）
│
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 FastAPI 装配、CORS、多租户 KV 中间件、/api/version
│  │  ├─ api/                    路由：events / accounts / tju / schedule / sync /
│  │  │                          attachments / calendar(ICS) / status / widgets / auth_ms
│  │  ├─ services/               sync_engine、scheduler、ics_export、events
│  │  ├─ connectors/             tju_cas / jw_eams / tju_schedule（解析）/ ms_todo / demo
│  │  ├─ models.py schemas.py db.py     SQLModel 模型与 Pydantic 出入参
│  │  ├─ security.py             会话鉴权、require_write、scope 绑定
│  │  ├─ captcha.py              SVG 验证码（HMAC 令牌 + KV 一次性 nonce）
│  │  └─ app_settings.py         KV 里的开关（注册门、邀请码等）
│  └─ tests/                     pytest，155 项，必须全绿
│
├─ android/
│  ├─ app/src/main/java/online/nzlab/schedule/
│  │  ├─ MainActivity.java       WebView 容器、资产拦截、原生 JS 桥（版本号/下载安装）
│  │  └─ TodayWidgetProvider.java 桌面小部件
│  ├─ app/src/main/assets/web/   前端产物（由 web/dist 拷贝而来，**不要手改**）
│  └─ app/build.gradle           versionCode / versionName / 签名
│
├─ deploy/
│  ├─ nginx/nzlab.online.schedule.conf   /schedule/ 的 location 片段
│  └─ systemd/                           campushub-sync.service
└─ HANDOVER.md                   本文件
```

---

## 3. 如何访问

### 3.1 线上（只读/体验）
- 网页 / PWA：`https://nzlab.online/schedule/`
- 健康检查：`https://nzlab.online/schedule/api/health`、`/api/version`
- API 文档：`https://nzlab.online/schedule/api/docs`（FastAPI 自动生成）
- APK：`https://nzlab.online/schedule/CampusHub.apk`

### 3.2 本地开发（不需要碰服务器）
```bash
cd E:/Agent_Workspace_Isolated/campussync

# 后端：另开一个终端
cd backend
pip install -r requirements.txt              # 首次
python -m uvicorn app.main:app --reload --port 8099
#   → http://127.0.0.1:8099/api/docs

# 前端
cd web
npm install                                   # 首次
npm run dev                                   # → http://127.0.0.1:5173
```

`web/vite.config.js` 的 dev 模式把 `/api` 代理到 `VITE_DEV_API`，默认 `http://127.0.0.1:8000`。若后端起在 8099，这样启动：

```bash
cd web && VITE_DEV_API=http://127.0.0.1:8099 npm run dev
```

### 3.3 服务器
```bash
ssh nzlab.online          # ~/.ssh/config 已配好：直连 IP + 经本地 SOCKS 代理
# 若报 "Unable to connect to relay host" → 本地 SOCKS 代理没起来，见 §7.1
```

服务器关键路径：
| 用途 | 路径 |
|---|---|
| 前端静态根 | `/var/www/schedule/frontend/`（nginx alias 到此） |
| 后端代码 | `/var/www/schedule/backend/app/` |
| venv | `/var/www/schedule/venv/` |
| 数据库 | `/var/www/schedule/data/campushub.db` |
| 环境变量 | `/var/www/schedule/.env`（**含机密，只读不打印**） |
| APK | `/var/www/schedule/CampusHub.apk` |
| 服务 | `systemctl {status,restart} campushub-sync`；日志 `journalctl -u campushub-sync -n 100` |
| nginx 片段 | 已 include 进 `/etc/nginx/sites-enabled/default`；源文件 `deploy/nginx/nzlab.online.schedule.conf` |

---

## 4. 如何修改这个网站

### 4.1 改 UI（90% 的需求都在这里）
1. 改 `web/src/` 下的文件；
2. `cd web && npm run dev` 看效果；
3. 跑测试：`node scripts/test_parse.mjs`、`node scripts/test_dedupe.mjs`；
4. `VITE_BASE=/schedule/ npm run build`；
5. 按 §5.1 部署。

**只改样式/文案**：一般只碰 `views/*.vue` 的模板与 `class`。项目统一用 Tailwind 原子类 + `dark:` 变体；磨砂玻璃（`backdrop-blur`）默认**关闭**且不在 UI 暴露开关（见 §7 红线）。

### 4.2 改接口
后端所有路由挂在 `/api` 前缀下（`backend/app/api/__init__.py` 汇总）。加接口：
1. 在对应 `api/*.py` 里加 `@router.get/post`；
2. 出入参走 `schemas.py` 的 Pydantic 模型；
3. 写操作要挂 `Depends(require_write)`（登录会话或 `X-Admin-Token` 均可）；
4. **多租户**：所有 KV 读写自动按请求方账号隔离（`main.py` 的 `bind_kv_scope` 中间件），新代码照常用 `KVStore()` 即可，不要绕开；
5. 补测试到 `backend/tests/`，跑 `python -m pytest tests -q`（应 155+ 全绿）。

### 4.3 改数据模型
`models.py` 加列 → `db.py` 的迁移段补 `ALTER TABLE`（本项目用轻量手写迁移，不用 Alembic）→ 同步改 `schemas.py` 与前端 `store.js`。提交前务必在本地副本 DB 上跑一次启动。

### 4.4 本地调试常用命令
```bash
# 后端测试（155 项）
cd backend && python -m pytest tests -q

# 前端解析/去重单测
cd web && node scripts/test_parse.mjs && node scripts/test_dedupe.mjs

# 版本号自查（六处必须一致）
grep -rn "2\.9\.0\|versionCode\|campushub-v" backend/app/main.py backend/app/api/status.py \
  web/public/sw.js android/app/build.gradle web/src/components/UpdateNotification.vue
```

---

## 5. 构建与部署

### 5.1 只发网页（最常见）
```bash
cd E:/Agent_Workspace_Isolated/campussync
VITE_BASE=/schedule/ npm --prefix web run build     # ⚠ VITE_BASE 绝不能漏，见 §7.2

tar czf /tmp/dist.tar.gz -C web/dist assets index.html sw.js
scp /tmp/dist.tar.gz root@108.186.202.38:/tmp/
ssh root@108.186.202.38 '
  set -e; cd /var/www/schedule
  rm -rf frontend.new && mkdir frontend.new
  tar xzf /tmp/dist.tar.gz -C frontend.new
  rm -rf frontend.old && mv frontend frontend.old && mv frontend.new frontend
  grep -o "src=\"[^\"]*\"" frontend/index.html'
```

原子切换（`frontend.new` → `frontend.old` → `frontend`）保证不会出现半截目录导致的 404 白屏。

**同步 Android 内置前端**（只在要发 APK 时才需要）：
```bash
rm -rf android/app/src/main/assets/web/assets android/app/src/main/assets/web/index.html
cp -r web/dist/assets android/app/src/main/assets/web/
cp web/dist/index.html web/dist/sw.js android/app/src/main/assets/web/
```

### 5.2 只发后端
```bash
tar czf /tmp/be.tar.gz backend/app
scp /tmp/be.tar.gz root@108.186.202.38:/tmp/
ssh root@108.186.202.38 'tar xzf /tmp/be.tar.gz -C /var/www/schedule && systemctl restart campushub-sync'
# 验证
curl -s https://nzlab.online/schedule/api/version
systemctl is-active campushub-sync
```

改了 `requirements.txt` 还要：`ssh ... '/var/www/schedule/venv/bin/pip install -r /var/www/schedule/backend/requirements.txt'`。

### 5.3 发 APK
```bash
export JAVA_HOME='E:/Alpha_nz_Files/_toolchain/jdk'
export ANDROID_HOME='E:/Alpha_nz_Files/_toolchain/android-sdk'
export PATH="/e/Alpha_nz_Files/_toolchain/jdk/bin:/e/Alpha_nz_Files/_toolchain/android-sdk/platform-tools:$PATH"
cd android && 'E:/Alpha_nz_Files/_toolchain/gradle-8.7/bin/gradle' assembleRelease --no-daemon

cd .. && cp android/app/build/outputs/apk/release/app-release.apk CampusHub.apk
# 校验版本号（必须与 build.gradle 一致）
'E:/Alpha_nz_Files/_toolchain/android-sdk/build-tools/<ver>/aapt2' dump badging CampusHub.apk | head -1

scp CampusHub.apk root@108.186.202.38:/var/www/schedule/CampusHub.apk
curl -sI https://nzlab.online/schedule/CampusHub.apk | grep -i "content-type\|content-length"
```

### 5.4 发版固定顺序（缺一步就会不一致）

```
1. 改代码 → 测试全绿
2. 批量升版本号（六处，见 §5.5）
3. VITE_BASE=/schedule/ 构建前端 → 注入 android assets
4. gradle assembleRelease → 拷 CampusHub.apk
5. 部署前端（§5.1）+ 部署后端（§5.2）+ 上传 APK
6. 线上验证：/api/version 版本号、JS/CSS 200、APK sha256 与服务端一致
7. git commit + push（§6）
8. gh release create vX.Y.Z ./CampusHub.apk（§6.3）
```

### 5.5 版本号六处（必须同时改）
| 文件 | 内容 |
|---|---|
| `backend/app/main.py` | `"version": "2.9.0"` / `"tag"` / `"title"` |
| `backend/app/api/status.py` | 同上（**容易漏，`/api/version` 实际读这里**） |
| `web/public/sw.js` | `const VERSION = 'campushub-v92'`（数字独立于版本号，每次 +1） |
| `android/app/build.gradle` | `versionCode 92` / `versionName "2.9.0"` |
| `web/src/components/UpdateNotification.vue` | `CURRENT_VERSION = '2.9.0'` |
| `HANDOVER.md` | 本文件顶部表格 |

同时把两份 `features`（`main.py` 与 `status.py`）换成新版本的更新要点——App 内的更新说明读这里。

---

## 6. 如何同步 GitHub

### 6.1 前置
- 仓库：`https://github.com/NoraNekowww/campushub-sync`，分支 `main`，`origin` 已配。
- `gh` 已登录 `NoraNekowww`。
- **直连 GitHub 不通**，走常开的 Clash Verge（`verge-mihomo`）混合端口 `127.0.0.1:7897`。它开机常驻，**不需要手动拉起**（以前的 v2rayN `30808` 已废弃）。

```bash
netstat -ano | grep LISTENING | grep 7897    # 有输出=代理在跑
curl -s -m 10 --proxy socks5h://127.0.0.1:7897 -o /dev/null -w "%{http_code}\n" https://github.com
```

### 6.2 提交与推送
```bash
cd E:/Agent_Workspace_Isolated/campussync
git add -A
git commit -m "feat: xxx (v2.9.1)"
git -c http.proxy=socks5h://127.0.0.1:7897 \
    -c https.proxy=socks5h://127.0.0.1:7897 push origin main
```

### 6.3 发 Release（挂 APK）
```bash
HTTPS_PROXY=socks5h://127.0.0.1:7897 HTTP_PROXY=socks5h://127.0.0.1:7897 \
  gh release create v2.9.1 ./CampusHub.apk \
  --title "CampusHub v2.9.1 — <一句话主题>" --notes-file /tmp/notes.md

gh release view v2.9.1 --json assets -q '.assets[] | "\(.name) \(.size)"'
```

> 注意：`CampusHub.apk` 在 `.gitignore` 里（`*.apk`），**不会进 git**，只挂在 Release 资产上；线上直链由 `scp` 单独推送到 VPS。

### 6.4 会被提交的东西
- ✅ `web/`、`backend/`、`android/`（含 `android/app/src/main/assets/web/` 的前端产物）、`deploy/`、文档
- ❌ `.env`、`*.apk`、`web/dist/`、`venv/`、`data/*.db`
- ⚠️ `android/app/src/main/assets/web/` 是**构建产物但要提交**，否则 APK 会打进旧页面。

---

## 7. 红线与已知坑（务必读）

### 7.1 SSH 报 `Unable to connect to relay host, errno=10061`
`~/.ssh/config` 的 `ProxyCommand` 走 `127.0.0.1:30808`。**不要手动开 v2rayN**——直接确认 Clash Verge 已在跑，并让 30808 有监听：

```bash
netstat -ano | grep LISTENING | grep 30808
# 没有输出就临时走 Clash 的 7897 直连一次：
ssh -o ProxyCommand='E:/PlatformIO/git/ucrt64/bin/connect.exe -S 127.0.0.1:7897 %h %p' nzlab.online
```

直连 22 端口是不通的（Cloudflare 挡了），别去掉代理。

### 7.2 白屏（最高频事故）
**根因**：漏了 `VITE_BASE=/schedule/`，`index.html` 引用 `/assets/index-xxx.js` 而线上实际在 `/schedule/assets/`。
**自查四连**：
```bash
curl -s https://nzlab.online/schedule/ | grep -oE 'src="[^"]+"'          # 必须以 /schedule/ 开头
curl -s -o /dev/null -w "%{http_code}\n" https://nzlab.online/schedule/assets/index-XXX.js   # 200
curl -s https://nzlab.online/schedule/api/version                        # 2.9.0
ssh nzlab.online 'ls /var/www/schedule/frontend/assets/'
```
修法：重新带 `VITE_BASE` 构建 + 重部署。用户侧再 `Ctrl+F5` / 重开 PWA。

### 7.3 APK 安装报 `PackageInfoIsNull`
`/schedule/CampusHub.apk` 必须有 nginx **精确 location**（`alias` 到 `/var/www/schedule/CampusHub.apk`）。若被 `location /schedule/` 的 `try_files` 兜底成 `index.html`，下载器存下的就是 HTML。替换 `frontend` 目录时别删这个文件。

### 7.4 实例不同步 / 数据被旧缓存冲掉
删除操作一律先写本地**墓碑**（`campushub.deleted_event_ids.v1`），后台 refresh、离线回写、周课表重载都要过墓碑过滤。新增改删逻辑必须复用这套机制，否则会出现「删了 2 秒后自己回来」。
用户手动改过的条目走 **Local-Wins**：上传失败时不允许被服务端旧数据覆盖。

### 7.5 课程重复出现两次
历史遗留的两套 event id 体系（学期同步 `hash(tju_schedule + "…w9:d2:p3-4:A202")` vs 直连导入 `hash(tju_schedule + "学期:课程:…")`）。已用前端内容去重收口：`web/src/utils/dedupe.js`，键 = 开始时间 + 标题 + 地点。**渲染/合并的任何新入口都要经过 `dedupeEvents()`**，不要再造第三套 id。

### 7.6 「无截止」逻辑是分离的两套
- 无截止待办（`is_undated=true`）：只在「可办事项」页由 `TodoQuickAdd.vue` 创建（只填标题+备注），**时间线 / DDL 列表 / 周课表 / ICS 全部排除**。
- 日程编辑器（`EventEditor.vue`）**不得**再出现「无截止」选项。加回会重新把两套逻辑搅在一起。

### 7.7 离线模式的边界
离线 = **不做账号云同步**，不是断网。`api.js` 的 `OFFLINE_ALLOWED = ['/version','/health','/tju/jw/local']`，其余请求直接短路。
课表导入走 `/api/tju/jw/local/captcha` + `/api/tju/jw/local/import`：服务器只代登一次教务、解析成事件数组返回，**不建账号、不落库、不存密码**，前端换算成本机事件。
附件在离线模式下存 data URL 到 localStorage：单文件 ≤2MB、合计 ≤4MB，不走 `/api/upload`。

### 7.8 其他约定
- **节数禁止按 `时长/45` 估算**，必须用 `EventOut.periods=[起,止]`（含课间的 4 节 = 210 分钟 ≈ 5 节，估算必错）。
- **教务周次位图第 1 位是报到周**，真实教学周 = 位次 − 1。
- **磨砂玻璃默认关闭且不在 UI 暴露开关**；主题色必须全系统联动（含课表日程块）。
- **窄列卡片地点不放 emoji 图钉**；顶底栏用紧凑纯图标。
- **附件卡片不显示文件大小/多余说明**；日程编辑器底部不放存储位置说明。
- **后台静默刷新不得覆盖用户当前正在编辑的内容**。
- 服务器 `.env` 含会话密钥/凭据加密密钥/微软客户端密钥，**永远不要把内容打印到终端或写进文档**。`.env.example` 里的值全是占位符。

---

## 8. 当前状态与下一步建议

**已完成到 v2.9.0 的能力**：天大教务一键导入（在线/离线）、多源待办同步（MS To Do）、ICS 订阅、PWA + 离线缓存、Android 内嵌离线开屏、自然语言识别建日程、重复日程、课程去重、可办事项独立成页、本地附件、外观主题/壁纸/磨砂。

**已知欠账（适合接手第一件事）**：
1. 真实学号完整教务导入未在交接环境实跑过（缺教务处密码），只跑了解析链的固定样本；
2. 浏览器自动化 UI 冒烟测试不稳定，建议补 Playwright + 真实登录态；
3. `store.js` 已是单体大文件，后续改动建议先按领域拆分再动逻辑。

---

*任何一步卡住：先按 §7 对应条目自查，再 `journalctl -u campushub-sync -n 100` 看后端日志。*
