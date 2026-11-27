# CampusHub Sync — Agent 交接手册（v3.0.3）

> **给接手开发的同学 / Agent**：这份文档是唯一入口。先确认环境（§0），再按 §4–§6 开发发布，动手前务必读完 §7「红线与已知坑」。
>
> | 项 | 值 |
> |---|---|
> | 当前版本 | `v3.0.3`（Android `versionCode 104`，`sw.js` `campushub-v104`） |
> | 下一版 | `v3.0.4`（versionCode `105`） |
> | 生产地址 | `https://nzlab.online/schedule/` |
> | APK 直链 | `https://nzlab.online/schedule/CampusHub.apk` |
> | 源码仓库 | `https://github.com/NoraNekowww/campushub-sync`（分支 `main`） |
> | 本地工作区 | `E:\Agent_Workspace_Isolated\campussync` |
> | VPS | `root@108.186.202.38`（SSH 若直连失败可走本地 Clash SOCKS5 `127.0.0.1:7897`） |
> | 更新日期 | 2026-11-27 |

---

## 0. 先跑起来：四条命令确认环境

```bash
cd E:/Agent_Workspace_Isolated/campussync
git status                                          # 应当干净
curl -s https://nzlab.online/schedule/api/version   # 应当返回 "version":"3.0.0"
cd web && node scripts/test_v300_scroll_and_persistence.mjs
```

---

## 1. 系统架构全景（v3.0.0）

面向大学生的**全屏课表 + 日程 + DDL + 可办事项同步系统**，一套 Vue 前端同时服务 Web/PWA 与 Android 客户端：

```
          ┌─────────────────────────────────────────────────────┐
          │ Android APK（Java + WebView + WebViewAssetLoader）  │
          │  • 本地 assets/web 0ms 离线秒开                     │
          │  • NativeAuthBridge: 手机直连教务 HTTP + 原子落盘存储│
          │  • 返回手势映射 window.__campushubHandleBack()       │
          └──────────────────────┬──────────────────────────────┘
                                 │ https://nzlab.online/schedule/api/* (keepalive + 双通道鉴权)
          ┌──────────────────────▼──────────────────────────────┐
          │  Vue 3 + Vite 5 + Tailwind（web/）                  │
          │  • 课表全屏全高斯模糊 + 单轴锁定滑动 + 0:00-24:00   │
          │  • 确定性主键（SHA-256 client_id）+ 单调时钟 LWW    │
          │  • 本地壁纸缓存（Built-in + Snap + CacheStorage）   │
          └──────────────────────┬──────────────────────────────┘
                                 │ HTTPS，Cookie + X-Session-Token 双通道
          ┌──────────────────────▼──────────────────────────────┐        ┌──────────────────────────┐
          │ FastAPI (uvicorn :8010) /var/www/schedule/backend   │───────▶│ 天大 SSO CAS + EAMS 教务  │
          │  • /api/events 确定性 upsert + client_updated_at    │        │ sso/classes.tju.edu.cn   │
          │  • /api/tju/jw/local/parse 手机直连 HTML 离线换算   │        └──────────────────────────┘
          └──────────────────────┬──────────────────────────────┘
                                 │
              SQLite /var/www/schedule/data/campushub.db
```

---

## 2. 目录结构与 v3.0.0 核心模块说明

```
campussync/
├─ web/
│  ├─ src/
│  │  ├─ api.js                        API 请求层（自动注入 Session/Admin Token、mutating keepalive:true、Date 响应头时钟偏差估算）
│  │  ├─ store.js                      全局响应式仓库（双写缓存 + 确定性 client_id + 0ms 立即回写 + 退后台冲刷）
│  │  ├─ App.vue                       全局背景渲染（0ms 缓存命中）、全屏课表容器、全局高斯模糊、返回键分发
│  │  ├─ style.css                     纯物理亚克力磨砂样式、45° 过去斜纹、呼吸冲突动画
│  │  ├─ views/
│  │  │  ├─ WeekView.vue               全屏无卡片课表：单轴方向锁定（touch/wheel）、惯性回弹、8:00-21:00 默认锚定、0-24:00 扩展、本周(默认)/今天第三列、DDL 线可点击
│  │  │  ├─ SettingsView.vue           二级菜单架构（课表与教务/外观与壁纸/账号与云同步/日历订阅/版本维护）；已导课表自动隐藏两步引导；「本周视图/今天在第三列」位于外观设置
│  │  │  ├─ AgendaView.vue             线性日程列表（仅 DDL / 仅日程 / 含课表 / 历史归档）
│  │  │  └─ TodoView.vue               无截止「可办事项」独立页
│  │  ├─ components/
│  │  │  ├─ ClassDetail.vue            课程与 DDL 共用详情卡（支持 DDL 倒计时、标星、编辑、直接划掉完成、删除）
│  │  │  ├─ EventEditor.vue            新建/编辑弹窗（区分待办 DDL 与时段活动日程、重复日程）
│  │  │  ├─ TjuConnect.vue             Android 在线/离线统一优先走手机直连教务 → /jw/local/parse → 本地或云端同步
│  │  │  ├─ UpdateNotification.vue     应用内更新检查与 APK 唤起下载
│  │  │  └─ ...
│  │  └─ utils/
│  │     ├─ lww.js                     同步 JS SHA-256 (`makeCustomEventId`)、单调时钟 `computeNextMutationIso`、`reconcileEventCollections` LWW+墓碑对齐引擎
│  │     ├─ dualStorage.js             Web localStorage + Android `NativeAuthBridge` 原子文件双写与冷启动对账合并
│  │     ├─ scrollLock.js              单轴意图判定 `resolveScrollAxis` 与水平整数列投影吸附 `projectColumnSnap`
│  │     ├─ wallpaperCache.js          默认本地壁纸 + localStorage 同步压缩快照 + CacheStorage (`campushub-wallpapers-v1`)
│  │     ├─ dedupe.js                  按 ID 归一 LWW，仅对外部课表源及遗留 `local_` 项做内容去重（互异正式 ID 的自建日程绝不误合并）
│  │     ├─ tjuNativeClient.js         手机直连 TJU CAS + EAMS 表单（`setting.kind=std`、`index`→`innerIndex`→`courseTable`、正确学期选择）
│  │     ├─ backNavigation.js          LIFO 返回栈，供 Android 返回键与桌面 Esc 调用
│  │     └─ datetime.js / note.js / themeColors.js / wallpapers.js / icsParser.js / parseScheduleText.js
│  ├─ public/
│  │  ├─ wallpapers/default-{light,dark}.jpg   内置默认高清壁纸（0ms 首帧命中，随 APK 与 SW 预缓存）
│  │  └─ sw.js                         Service Worker（跨版本保留 `campushub-wallpapers-v1`，图片 cache-first）
│  └─ scripts/
│     ├─ test_parse.mjs                55 项自然语言识别单测
│     ├─ test_dedupe.mjs               10 项去重单测
│     ├─ test_lww.mjs                  6 项 LWW 逻辑单测
│     ├─ test_v295_utils.mjs           3 项工具单测
│     ├─ test_tju_native.mjs           6 项手机直连 CAS/EAMS 模拟单测
│     ├─ test_v298_sync_and_cache.mjs  6 项确定性 ID、LWW 墓碑与壁纸缓存单测
│     └─ test_v300_scroll_and_persistence.mjs  单轴滑动锁定与 Android 双写恢复单测
│
├─ backend/
│  ├─ app/
│  │  ├─ main.py                       FastAPI 装配、CORS、KV 多租户中间件、/api/version
│  │  ├─ schemas.py                    EventCreateIn（含 `client_id`/`client_ids`/`client_updated_at`）与 EventPatchIn
│  │  ├─ api/events.py                 `list_events(include_hidden=...)`、`create_event` 幂等确定性 upsert、`update_event`/`delete_event` LWW 时间戳防倒流
│  │  ├─ services/events.py            `effective_updated_at` 与受保护字段更新
│  │  └─ services/sync_engine.py       外部源 upsert 严守 `local_override` 保护字段
│  └─ tests/
│
├─ android/
│  ├─ app/src/main/java/online/nzlab/schedule/MainActivity.java
│  │  ├─ WebViewAssetLoader（`.html/.js/.css/.jpg/.svg/.webp`）
│  │  ├─ AuthBridge：CAS/EAMS 原生 HTTP、版本查询、APK 下载安装、Tokens 备份
│  │  └─ **原生原子存储**（`readNativeStore`/`writeNativeStore`/`removeNativeStore`/`clearNativeStore`，写 `.tmp` + `getFD().sync()` + `renameTo`，`onPause`/`onStop`/`onDestroy` 阻塞刷盘至 `filesDir/campushub_store/*.json`）
│  └─ app/build.gradle                 `versionCode 101` / `versionName "3.0.0"`
│
└─ deploy/                             nginx 与 systemd 配置
```

---

## 3. 如何本地运行与验证

### 3.1 本地跑全套前端单测与编译
```bash
cd E:/Agent_Workspace_Isolated/campussync
node web/scripts/test_parse.mjs
node web/scripts/test_dedupe.mjs
node web/scripts/test_lww.mjs
node web/scripts/test_v295_utils.mjs
node web/scripts/test_tju_native.mjs
node web/scripts/test_v298_sync_and_cache.mjs
node web/scripts/test_v300_scroll_and_persistence.mjs

# 构建前端并同步进 Android assets（绝对不能漏 VITE_BASE=/schedule/）
export VITE_BASE=/schedule/
npm --prefix web run build
```

### 3.2 后端开发与校验
```bash
cd E:/Agent_Workspace_Isolated/campussync/backend
python -m py_compile app/main.py app/schemas.py app/api/events.py app/api/status.py app/services/events.py app/services/sync_engine.py
python -m uvicorn app.main:app --reload --port 8099
```

### 3.3 Android 打包
```bash
export JAVA_HOME='E:/Alpha_nz_Files/_toolchain/jdk'
export ANDROID_HOME='E:/Alpha_nz_Files/_toolchain/android-sdk'
cd E:/Agent_Workspace_Isolated/campussync/android
'E:/Alpha_nz_Files/_toolchain/gradle-8.7/bin/gradle.bat' assembleRelease --no-daemon
cp app/build/outputs/apk/release/app-release.apk ../CampusHub.apk
'E:/Alpha_nz_Files/_toolchain/android-sdk/build-tools/34.0.0/aapt2.exe' dump badging ../CampusHub.apk | head -n 1
```

---

## 4. 部署、发版与 GitHub 同步流程

### 4.1 必须同步更新的 7 处版本号
每次发版前统一检索并更新：
1. `backend/app/main.py`（`/api/version` 的 `version`/`tag`/`title`/`features`）
2. `backend/app/api/status.py`（`/api/version` Router，线上实际命中这里）
3. `web/public/sw.js`（`const VERSION = 'campushub-vXXX'`）
4. `android/app/build.gradle`（`versionCode` + `versionName`）
5. `web/src/components/UpdateNotification.vue`（`CURRENT_VERSION`）
6. `web/src/views/SettingsView.vue`（`clientAppVersion` 兜底返回值）
7. `HANDOVER.md`（顶部版本表）

### 4.2 服务器部署路径与校验
- VPS IP：`108.186.202.38`（如直连受阻，加 `-o "ProxyCommand=E:/PlatformIO/git/ucrt64/bin/connect.exe -S 127.0.0.1:7897 %h %p"`）。
- nginx 对 `/schedule/` 使用 `alias /var/www/schedule/frontend/`（**不是** `/var/www/schedule/web/dist/`！发版时建议同步更新 `/var/www/schedule/frontend/` 与 `/var/www/schedule/web/dist/`，同时绝不要把 `CampusHub.apk` 留在 `frontend/` 下）。
- APK 精确路径：`/var/www/schedule/CampusHub.apk`。
- 后端目录：`/var/www/schedule/backend/app/`；重启命令：`systemctl restart campushub-sync && systemctl is-active campushub-sync`。
- **绝对红线**：永远不要读取、打印或写入 `/var/www/schedule/.env` 的真实密钥！

### 4.3 GitHub 推送与 Release
- 若直连 GitHub 超时，配置环境代理 `ALL_PROXY=socks5h://127.0.0.1:7897` / `HTTPS_PROXY` / `HTTP_PROXY`。
- `CampusHub.apk` 在 `.gitignore` 内不进 git，作为 `gh release create vX.Y.Z ./CampusHub.apk` 附件上传，并与本地及 VPS SHA256 比对一致。

---

## 5. 红线与关键技术约定（切勿破坏）

1. **`VITE_BASE=/schedule/` 严禁遗漏**：否则线上访问 `/schedule/` 时资源加载 404 白屏。
2. **Android 端数据持久化走双写通道（`dualStorage.js` + `MainActivity.writeNativeStore`）**：任何新增持久化本地缓存字段或修改保存流程，必须同步更新 `ALLOWED_STORE_KEYS` 与双写函数，不要退回纯 `localStorage` + `setTimeout` 延迟提交（Android WebView 被划掉时 Chromium LevelDB 缓冲可能尚未落盘）。
3. **自建日程确定性主键与单调 LWW**：前端创建时直接通过 `makeCustomEventId(sourceId)` 生成与后端一致的 32 位主键，并携带 `client_id` / `client_updated_at` 提交；`GET /api/events` 默认传入 `include_hidden=true` 供客户端按 ID + 时间戳合并墓碑，**不要去掉 `include_hidden` 或在 `dedupe.js` 中对不同正式 ID 的 `custom` 日程按标题合并**。
4. **教务抓取链路**：海外 VPS 直连天大 CAS 会超时（TCP timeout）；Android 客户端（无论在线还是离线模式）在 `TjuConnect.vue` 中统一优先走 `runNativeImport` 手机直连抓取 + `/api/tju/jw/local/parse`（+ 在线模式下 `POST /api/tju/import`），不要把在线模式切回纯服务端抓取。
5. **课表交互与布局约定**：
   - `WeekView.vue` 采用 JS 单轴锁定（水平切换列 vs 竖直浏览 0:00–24:00），不要随意加回 `snap-x` CSS 或 `touch-action: none`（会与触摸锁定及点击触发冲突）。
   - 课表无外层 `.card` 包裹、背景全屏高斯模糊；默认视图模式为「本周视图（周一在第一列）」，可选「今天在第三列」，入口位于「设置 → 外观与壁纸」。
   - DDL 实线热区（24px）需保持高于普通课程块（`z-20`）且可点击打开 `ClassDetail.vue` 进行编辑与划掉完成。
6. **「无截止」可办事项与普通日程分离**：`is_undated=true` 仅由 `TodoQuickAdd.vue` 管理，禁止加回 `EventEditor.vue`。

---

## 6. 给下一任 Agent 的接续建议

1. **真实手机端到端真机回归（推荐优先）**：
   - 用 Android 真机（`adb logcat` + Chrome `chrome://inspect`）安装 `CampusHub.apk` v3.0.0 实测：
     - 新建日程后立即划掉后台多任务重启 App，确认 `files/<pkg>/campushub_store/events_cache.json` 与 `sync_queue.json` 毫秒级生效且重启不丢失；
     - 实测课表斜向滑动与快速甩动的手感阈值（当前死区 `6px`、惯性衰减 `0.94`）；
     - 用真实天大学号密码分别测试离线/在线一键导课表。
2. **线上浏览器完整登录态冒烟测试**：当前生产静态页与接口已自动检查，可补充带上测试账号的 Playwright 线上全流程验收，顺便检验 `v3.0.0` 应用内更新弹窗在旧版客户端的弹出效果。
3. **`TodayWidgetProvider.java` 桌面小部件数据源升级**：当前桌面小部件仍通过 HTTP 请求接口，后续可考虑复用到 `campushub_store/events_cache.json` 做更快的离线渲染。
4. **`store.js` 模块化拆分**：随着业务增长（当前约 2200 行），建议拆分为 `stores/events.js`、`stores/auth.js`、`stores/appearance.js`、`stores/tju.js` 以降低单文件维护成本。
