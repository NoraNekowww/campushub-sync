# CampusHub Sync

把**微软 To Do 的任务/DDL**和**天津大学课表**聚合成一条干净的时间线，用手机 PWA 看，并提供一个
**iCalendar（.ics）订阅地址**，让系统日历（iOS / Android / Outlook / GNOME）自动同步。

- 后端：FastAPI + SQLModel(SQLite) + APScheduler，后台每 20 分钟增量同步
- 前端：Vite + Vue 3 + TailwindCSS + Lucide，PWA（manifest + service worker，可离线看缓存课表）
- 访问控制：**账号系统**（注册/登录/邀请码/管理员/停用）——登录墙在 App 里，账号入口在门户右上角
- 部署：VPS 上以 **venv + systemd** 跑单进程（监听 127.0.0.1:8010），Nginx 挂在
  `https://nzlab.online/schedule/`（子路径，与既有站点同 server 块）；也提供 Docker 方案
- 设计取向：**单进程**（FastAPI 同时提供 `/api/*` 和编译好的前端）、**少依赖**（账号系统只用标准库 crypto）、
  **读/写权限分离**

---

## 1. 目录结构

```
campushub-sync/
├── backend/                        # FastAPI 服务
│   ├── app/
│   │   ├── main.py                 # 应用工厂：挂载 /api、静态 PWA、启动调度器
│   │   ├── config.py               # pydantic-settings 配置（.env）
│   │   ├── models.py               # SQLModel 统一事件模型 + 枚举
│   │   ├── schemas.py              # API 出入参模型（含 CountsOut）
│   │   ├── db.py                   # engine/session + KV 表（存 refresh_token 等）
│   │   ├── security.py             # 令牌 + 账号会话的统一守卫（require_read/write/account）
│   │   ├── accounts.py             # 账号核心：PBKDF2 口令、HMAC 会话 Cookie、登录限流
│   │   ├── timeutil.py             # 时区工具（存储 UTC、展示 Asia/Shanghai）
│   │   ├── api/                    # 路由层
│   │   │   ├── accounts.py         # /api/auth/{session,register,login,logout,me,password,users}
│   │   │   ├── events.py           # GET/POST/PATCH/DELETE /api/events
│   │   │   ├── calendar.py         # GET /api/subscribe/calendar.ics（RFC 5545）
│   │   │   ├── sync.py             # POST /api/sync（手动触发）
│   │   │   ├── status.py           # GET /api/status|/api/config|/api/logs
│   │   │   ├── auth_ms.py          # POST /api/auth/ms（设备代码流）
│   │   │   └── schedule.py         # POST /api/schedule（上传 ICS / 学期设置）
│   │   ├── connectors/             # 外部数据源
│   │   │   ├── base.py             # 连接器基类：重试/退避/抖动/错误分类
│   │   │   ├── ms_todo.py          # MSAL 机密客户端 + Graph To Do + 令牌自动刷新
│   │   │   ├── tju_schedule.py     # 微北洋(WePeiyang)抓取 + 静态 ICS 兜底
│   │   │   └── demo.py             # DEMO_MODE=1 时的合成数据
│   │   └── services/
│   │       ├── sync_engine.py      # 抓取 → 规范化 → upsert（不覆盖本地状态）→ 清理
│   │       ├── events.py           # 事件查询/落库/过期清理
│   │       ├── ics_export.py       # ics 生成 + ETag
│   │       └── scheduler.py        # APScheduler 装配
│   ├── tests/                      # pytest（63 项，含越权探测）
│   ├── requirements.txt
│   └── pytest.ini
├── web/                            # 前端 PWA
│   ├── src/
│   │   ├── App.vue  main.js        # 外壳、视图切换、离线与主题
│   │   ├── api.js   store.js       # 极简 API 客户端 + reactive 状态（无 Pinia）
│   │   ├── utils/datetime.js       # 上海时区日期工具（不依赖设备时区）
│   │   ├── views/                  # AgendaView / WeekView / SettingsView
│   │   └── components/             # 卡片、筛选、底栏、骨架屏、详情弹层、AuthGate（登录墙）
│   ├── public/{manifest.webmanifest, sw.js, icons/}
│   ├── index.html  vite.config.js  tailwind.config.js
├── deploy/
│   ├── install.sh                  # VPS 一键安装/升级（venv → systemd → nginx → 生成 .env）
│   ├── systemd/campushub-sync.service
│   ├── nginx/nzlab.online.schedule.conf   # 插进既有 server 块的 /schedule/ 片段
│   ├── nginx/schedule.nzlab.online.conf   # 独立子域方案（可选）
│   └── portal/index.html           # 门户首页（含右上角账号区）
├── tools/
│   ├── make_icons.py               # 零依赖生成 PWA 图标
│   ├── smoke_test.py               # 对运行中的实例做 34 项端到端检查
│   ├── check-feed-hide.py          # 线上自检：删一条日程 → 订阅日历里消失 + 墓碑（跑完自动撤销）
│   ├── encrypt_kv_secrets.py       # 凭据迁移/巡检（--check / --dry-run）
│   ├── t_e2e_user.py               # 建/删临时账号（--cleanup 连它的日程一起清）
│   └── visual/                     # puppeteer-core + 系统 Edge 的无头校验
│       ├── verify-ui.mjs           # 三个视图的 23 项 UI 检查
│       ├── verify-auth.mjs         # 登录墙 → 注册 → 持久化 → 退出（13 项）
│       └── verify-portal.mjs       # 线上门户账号区 + /schedule/ 联动（16 项）
├── web/tools/                      # 前端侧的线上校验（同一套 headless Edge 套路）
│   ├── verify-swipe-delete.mjs     # 卡片左右滑动删除 + 撤销 + 划掉未被手势吃掉
│   ├── verify-tju-ui.mjs           # 真账号回归：教务绑定面板
│   └── verify-panel.mjs            # 设置页渲染 + 底部反馈链接
├── Dockerfile  docker-compose.yml  .dockerignore  .env.example
└── README.md
```

---

## 2. 快速开始

### 2.1 Docker（推荐，就是 VPS 上的形态）

```bash
git clone <your-repo> campushub-sync && cd campushub-sync
cp .env.example .env
# 生成两个互不相干的密钥
python -c "import secrets;print('ADMIN_TOKEN='+secrets.token_urlsafe(32))"
python -c "import secrets;print('SUBSCRIBE_TOKEN='+secrets.token_urlsafe(32))"
$EDITOR .env                     # 粘贴进 .env，填 PUBLIC_BASE_URL
docker compose up -d --build
docker compose logs -f backend   # 应看到 "CampusHub Sync v1.0.0 ready"
curl -s http://127.0.0.1:8000/api/health
```

### 2.2 本地开发（Windows / macOS / Linux）

```bash
python -m venv .venv && source .venv/Scripts/activate     # PowerShell: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cd web && npm install && npm run build && cd ..
cd backend
DEMO_MODE=1 TJU_MODE=demo \
  ADMIN_TOKEN=dev-admin-token SUBSCRIBE_TOKEN=dev-subscribe-token \
  PUBLIC_BASE_URL=http://127.0.0.1:8000 SYNC_ON_STARTUP=1 \
  uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000/?token=dev-admin-token> —— 用 `?token=` 打开一次即可，令牌会写入
`localStorage` 并从地址栏抹掉（避免截图/历史记录泄露）。`DEMO_MODE=1` 会生成一批相对
“今天”的示例课程与 DDL，方便先看界面。

自检：

```bash
./.venv/Scripts/python.exe tools/smoke_test.py --base http://127.0.0.1:8000 \
    --admin-token dev-admin-token --subscribe-token dev-subscribe-token   # 34 项
cd tools/visual && npm install && node verify-ui.mjs --base http://127.0.0.1:8000 \
    --token dev-admin-token                                               # 24 项 + 截图
```

---

## 3. 配置项（`.env` 摘要，完整见 `.env.example`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ADMIN_TOKEN` | 空 | 管理令牌：读取 + 写入（**生产必须设置**） |
| `SUBSCRIBE_TOKEN` | 空 | 只读令牌：日历订阅、分享链接；不能改数据 |
| `PUBLIC_BASE_URL` | `https://schedule.nzlab.online` | 生成订阅地址用，必须能从手机访问 |
| `DATA_DIR` | `./data` | SQLite + 令牌文件所在目录（compose 里是 `/app/data`） |
| `WEB_DIST` | `../web/dist` | 前端构建产物目录 |
| `SYNC_INTERVAL_MINUTES` | `20` | 后台同步周期（建议 15–30） |
| `SYNC_ON_STARTUP` / `ENABLE_SCHEDULER` | `true` | 启动即同步 / 是否启用调度器 |
| `EVENT_RETENTION_DAYS` | `30` | 清理过了多久的旧事件（`source=custom` 不动） |
| `DEMO_MODE` / `TJU_MODE` | `false` / `ics` | 演示数据 / 课表来源：`ics`・`wepeiyang`・`demo` |
| `MS_CLIENT_ID` `MS_CLIENT_SECRET` `MS_TENANT_ID` | 空 | Azure 应用注册（机密客户端） |
| `MS_SCOPES` | `Tasks.ReadWrite offline_access` | Graph 权限 |
| `SEMESTER_START_DATE` `TJU_PERIOD_TIMES_JSON` | — | 学期第 1 周周一 / 节次时间表 |
| `TJU_ICS_PATH` `TJU_WEPEIYANG_TOKEN` | — | 静态课表文件 / 微北洋令牌 |
| `SESSION_SECRET` | 空（自动生成 `data/session.secret`） | 会话签名密钥；换掉 = 所有人重新登录 |
| `CREDENTIAL_KEY` | 空（自动生成 `data/credential.key`） | **加密存储凭据**（教务密码/微软令牌/邀请码）的密钥；换掉或丢失 = 已存凭据全部作废，用户需重填 |

未设置 `ADMIN_TOKEN` 时服务会**放行全部请求**（仅适合本地预览）；启动日志会明确警告。

---

## 4. 数据来源对接

### 4.1 微软 To Do（MSAL 机密客户端 + 设备代码流）

1. Azure Portal → 应用注册 → 支持账户类型选“任何组织目录/个人 Microsoft 账户”。
2. 添加**机密客户端**，记录 `客户端 ID`、`客户端密码`、`目录(租户) ID` → 写入 `.env`。
3. API 权限添加**委托**权限：`Tasks.ReadWrite`、`offline_access`（Graph）。
4. 前台授权一次：
   - 网页：**设置 → 微软 To Do → 开始设备代码登录**，按提示在 `microsoft.com/devicelogin` 输入代码；
   - 或者 curl：
     ```bash
     curl -s -X POST localhost:8000/api/auth/ms -H "X-Admin-Token: $ADMIN_TOKEN" \
          -H 'Content-Type: application/json' -d '{"action":"start"}'
     curl -s -X POST localhost:8000/api/auth/ms -H "X-Admin-Token: $ADMIN_TOKEN" \
          -H 'Content-Type: application/json' -d '{"action":"poll"}'
     ```
5. 令牌落在 `data/ms_token.json`（权限 `0600`、原子写入），含 `refresh_token`；
   访问令牌过期时用 MSAL 静默刷新，`refresh_token` 轮换后立即回写。刷新失败 → 连接器标记
   `reauthorize_required`，`/api/status` 会提示重新登录，**不会**拖垮其他连接器。

映射规则：`dueDateTime` → `start_time`（`is_deadline=true`）、`reminderDateTime` → 日历 `VALARM`、
`importance` → 优先级标签、列表名 → 分类。

### 4.2 天津大学课表

微北洋的接口不是「一个地址 + 一个令牌」那种，下面这些是**实测 + 对照官方开源客户端源码**
（`twtstudio/WePeiYang-Android`）反出来的结论：

| 上游 | 用途 | 可达性 |
| --- | --- | --- |
| `open.twt.edu.cn/api` | 现在的开放平台：`GET /v1/auth/token/get`（登录）、`GET /v1/classtable`（课表） | **仅校园网**。校外一律 `302 → network-notice.tju.edu.cn`（页面上写着「该网页目前只允许校内访问」） |
| `api.twt.edu.cn` | 旧 REST 接口，只剩登录可用：`POST /api/auth/common` | 公网可达，但必须带客户端身份头 `ticket` + `domain`（否则 `50003 未绑定的url`） |
| `jw.tju.edu.cn` / `e.tju.edu.cn` | 教务系统 / 融合门户 | 校园网内，服务器（本机在洛杉矶）不可达 |
| `sso.tju.edu.cn/cas/login` | 统一身份认证 | 公网可达，但登录需要验证码 + RSA 加密，不适合脚本化 |

开放平台的请求要签名（App-Key 与算法是官方客户端里的公开常量，浏览器端实现见
`web/src/twt-sign.js`，与后端 `connectors/tju_api.py` 的 SHA-1 结果逐字节一致）：

```
sign = SHA1(APP_KEY + "".join(name + value for sorted params) + APP_SECRET).upper()
GET  /v1/classtable?t=<ms>&sign=<…>&app_key=<…>     头: Authorization: Bearer<token>
```

**因为课表只对校园网开放，服务器永远拉不到**，所以是「两条腿」：

**方式 A — 网页端直连（推荐，`TJU_MODE=imported`）**
在 **设置 → 天津大学课表 → 微北洋直连** 里填学号 + 微北洋密码，点
**「在我的浏览器里抓取（校园网）」**：登录与拉取都由**你自己的浏览器**发（连着校园网时），
解析后 POST 给 `POST /api/tju/import` 入库；**密码不经过服务器**。
若浏览器被 CORS 拦（少见），面板里的「手动兜底」给出两条链接/一段控制台脚本，把 JSON 粘回来即可。

**方式 B — 服务器侧（学号密码 / 令牌）**
`POST /api/tju/credentials` 可以用学号密码登录（走公网可达的旧接口）并把令牌存进库，
然后 `POST /api/tju/sync` 尝试服务器直连。**不在校园网时会明确返回
`{"kind":"campus_network"}`**，而不是假装成功 —— 这也正是面板上「让服务器试着抓」的含义。

**方式 C — 静态 ICS / 手粘 JSON 兜底**：`TJU_MODE=ics` 上传 `tju.ics`（`POST /api/schedule/upload`），
或在同一个面板里直接粘贴 `v1/classtable` 的 JSON（也可以从微北洋 App 缓存
`shared_prefs` 里的 `schedule2_tju_classtable` 取）。

> 学期第一周周一优先取接口返回的 `term_start`（真实值），其次才是 `SEMESTER_START_DATE`。
> 首次导入时，带「（演示）」标记的演示事件会被自动清掉，并重建同步引擎。

---

## 5. API

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/health` | 公开 | 存活探针 |
| GET | `/api/events` | 读令牌 | 参数 `start_date` `end_date`（含当天）`source` `status` `limit` `offset` |
| POST | `/api/events` | 管理令牌 | 新建 `source=custom` 事件 |
| PATCH | `/api/events/{id}` | 管理令牌 | 改标题/时间/`status`（打勾完成）/`hidden`（软删除开关，`false` 即撤销删除） |
| DELETE | `/api/events/{id}` | 管理令牌 | **软删除**：把日程从时间线与订阅日历里拿掉（返回体里 `hidden: true`），可撤销；不再拒绝外部来源 |
| GET | `/api/subscribe/calendar.ics?token=…` | 订阅令牌 | RFC 5545 订阅源，带 `VEVENT`+`VALARM`，支持 `If-None-Match`/304；默认**只发站长自己的**、且**不含已划掉/已删除**的日程（见下） |
| POST | `/api/sync` | 管理令牌 | 手动触发同步，返回 `fetched/created/updated/pruned` |
| GET | `/api/status` | 读令牌 | 健康、上次同步、各连接器状态、统计计数 |
| GET | `/api/config` | 读令牌 | 前端初始化配置（订阅地址、周期、是否演示模式） |
| GET | `/api/logs` | 管理令牌 | 最近同步日志 |
| POST | `/api/auth/ms` | 管理令牌 | `{"action":"start"|"poll"|"status"}` 设备代码流 |
| POST | `/api/schedule` | 管理令牌 | 上传/删除 ICS 课表、写入学期设置 |
| GET | `/api/tju/status` | 读令牌 | 微北洋凭据/导入状态；`?probe=true` 顺带探一次校园网可达性 |
| POST | `/api/tju/credentials` | 管理令牌 | `{"mode":"password"\|"token", …}` 登录并保存令牌（旧接口可从公网登录） |
| DELETE | `/api/tju/credentials` | 管理令牌 | 删除已保存令牌 |
| POST | `/api/tju/sync` | 管理令牌 | 服务器侧尝试抓课表；校园网限制时返回 `{"ok":false,"detail":{"kind":"campus_network"}}` |
| POST | `/api/tju/import` | 管理令牌 | 接收 `v1/classtable` 的 JSON（`payload` 对象或 `text` 原文）→ 入库并立即同步 |
| DELETE | `/api/tju/import` | 管理令牌 | 清除已导入课表 |
| GET | `/api/auth/session` | 公开 | 当前登录状态 + 账号开关（前端/门户据此渲染登录或登录墙） |
| POST | `/api/auth/register` | 公开（需邀请码） | 注册并直接建立会话；**第一个账号自动成为管理员** |
| POST | `/api/auth/login` | 公开 | 登录，下发 HttpOnly 会话 Cookie（失败有次数限流） |
| POST | `/api/auth/logout` | 公开 | 退出，清 Cookie |
| GET | `/api/auth/me` | 登录账号 | 当前账号信息 |
| POST | `/api/auth/password` | 登录账号 | 修改自己的密码 |
| GET | `/api/auth/users` | 管理员 | 成员列表 |
| PATCH | `/api/auth/users/{id}` | 管理员 | 停用/启用成员、调整角色 |

### 日程能划掉、能删掉，系统日历里就跟着消失

- **划掉（打勾）**：`PATCH /api/events/{id} {"status":"completed"}` —— 时间线里保留（带删除线，
  可再勾回来），但**订阅出去的日历里默认不再出现**。
- **删掉**：`DELETE /api/events/{id}` 是**软删除**（`hidden=true`），不再是物理删除 ——
  课表里的课、微软待办的任务也能删（以前会 409），删了之后同步不会把它拉回来
  （会一并置 `local_override`），撤销 = `PATCH {"hidden": false}`。
- **为什么还发一条 `STATUS:CANCELLED`**：订阅源里「单纯不再出现」的条目，部分客户端会
  一直留着；对 45 天内删掉/刚划掉的日程再发一条同 `UID` 的 `STATUS:CANCELLED` 墓碑，
  客户端才会真的把它从手机日历里删掉。响应头 `X-Event-Count` / `X-Cancelled-Count`
  分别给出「可见」与「墓碑」条数。
- **只发站长自己的**：订阅令牌是站长（owner）的，feed 只导出他名下的日程；多租户之后
  别人的课表不会混进他的手机日历。想要「已完成也留着」用 `?include_completed=true`。
- `STATUS:CONFIRMED` 是 VEVENT 唯一说得通的「在办」状态（RFC 5545 的 `COMPLETED` 只属于
  VTODO，塞进 VEVENT 客户端多半直接丢掉）。

### 三种凭据与权限

| 凭据 | 授予 | 用法 |
| --- | --- | --- |
| 账号会话 Cookie | **读**（`user`）、读+写（`admin`） | 浏览器登录后由 `/schedule/api/*` 自动携带；HttpOnly、SameSite=Lax、14 天 |
| `ADMIN_TOKEN` | 读 + 写 + 管理 | 脚本/CI 用 `X-Admin-Token` 头 |
| `SUBSCRIBE_TOKEN` | 只读 | `.ics` 订阅地址的 `?token=`（日历客户端加不了头） |

- 守卫在 `app/security.py`：`require_read`（管理员令牌 / 订阅令牌 / 任意登录账号）、
  `require_write`（管理员令牌 / **管理员账号**）、`current_account` / `current_admin`（端点内取当前账号）。
- 账号是纯标准库实现：PBKDF2-HMAC-SHA256（26 万轮 + 16 字节盐），会话是 HMAC-SHA256 签名的
  `v1.<账号>.<过期>.<签名>`，密钥首次启动生成到 `data/session.secret`（0600）。
- `tests/test_access_control.py` 会**遍历 OpenAPI 里所有写接口**，以匿名身份逐个探测，
  只要有一个返回 200/201/422（即没被拦下）就整个测试失败 —— 新增路由忘记加守卫会被 CI 抓到。

令牌传递：`X-Admin-Token` / `X-Subscribe-Token` 请求头，或 `Authorization: Bearer <token>`；
`/api/subscribe/calendar.ics` 只认 query 参数 `token`（因为日历客户端不方便加头）。
**只读令牌永远无法写入**——所有变更接口只认 `ADMIN_TOKEN`（`tools/smoke_test.py` 会验证这一点）。

### 日历订阅

- iOS：设置 → 日历 → 账户 → 添加账户 → 其他 → 添加已订阅的日历，粘贴 `.ics` 地址
- Android：Google 日历网页版 → 其他日历 → 通过网址订阅（原生 App 不支持）
- Outlook / Thunderbird / GNOME 日历：直接“订阅日历”，填 `webcal://…` 地址
- 地址在 **设置 → 日历订阅** 里一键复制（同时给出 `https://` 与 `webcal://` 两种形式）

---

## 6. 部署到 nzlab.online（已完成）

生产形态：**同一台 VPS、同一个 `default` server 块、子路径 `/schedule/`**。
之所以不用 Docker：那台机器只有 925 MB 内存 / 5 GB 空闲磁盘，且 `127.0.0.1:8000` 已被 cycle 项目占用；
所以本服务用 venv + systemd 跑在 `127.0.0.1:8010`，Nginx 只做两件事：静态文件 + `/schedule/api/` 反代
（`proxy_pass … /api/` 会把 `/schedule` 前缀剥掉，后端因此仍能独立跑在 localhost）。

```bash
# 1) 本机打包（前端用子路径构建！）
cd web && VITE_BASE=/schedule/ npm run build && cd ..
tar czf campushub-release.tar.gz -C <staging> .        # backend/ frontend/ tools/ deploy/

# 2) 上传并安装
scp campushub-release.tar.gz root@nzlab.online:/tmp/
ssh root@nzlab.online 'mkdir -p /var/www/schedule && tar xzf /tmp/campushub-release.tar.gz -C /var/www/schedule'
ssh root@nzlab.online 'bash /var/www/schedule/deploy/install.sh'
```

`deploy/install.sh` 是幂等的：建 venv、装依赖、生成 `.env`（首次，含随机令牌与邀请码）、
装 systemd 单元并启动、把 `deploy/nginx/*.conf` 装到 `/etc/nginx/snippets/`、
**备份后**把 `include` 插进 `sites-available/default` 的 443 server 块末尾，最后 `nginx -t && reload`。
重跑它只升级代码、重启服务，**不会覆盖已有 `.env`**。

日常运维：

```bash
systemctl status campushub-sync       # 服务状态
journalctl -u campushub-sync -f       # 日志（同步结果、登录失败都在这）
systemctl restart campushub-sync      # 改完 .env 之后
tar czf ~/schedule-$(date +%F).tgz -C /var/www/schedule data   # 备份（.db + 会话密钥）
```

### 部署后的状态

| 项目 | 值 |
| --- | --- |
| 站点 | `https://nzlab.online/schedule/` （PWA 可「添加到主屏幕」） |
| 门户 | `https://nzlab.online/` （右上角账号区，日程表卡片带「需登录」标记） |
| 后端 | `127.0.0.1:8010`，systemd 单元 `campushub-sync`（enabled，开机自启） |
| 代码 | `/var/www/schedule/{backend,frontend,tools,deploy}` + `venv/` + `data/` |
| 配置 | `/var/www/schedule/.env`（0600）：`ADMIN_TOKEN` / `SUBSCRIBE_TOKEN` / `REGISTRATION_INVITE_CODE` |
| Nginx | `/etc/nginx/snippets/campushub-sync.conf`，由 `sites-available/default` 末尾 include |
| 回滚 | `/etc/nginx/sites-available/default.bak.*`、`/var/www/portal/index.html.bak.*` |

> **演示数据**：首次部署 `.env` 里是 `TJU_MODE=demo` + `DEMO_MODE=true`，所以打开就有 16 条带「（演示）」
> 字样的事件，方便确认链路通。**接真实课表不再需要改 `.env`**：在「设置 → 天津大学课表 → 微北洋直连」
> 里完成一次导入即可（导入会把模式写进 KV、自动清掉这 16 条演示事件、并重建同步引擎）。
> 若想手工切换，改成 `TJU_MODE=imported`（或 `ics`）、`DEMO_MODE=false` 再
> `systemctl restart campushub-sync`。

### 门户右上角的账号区

门户首页（`/var/www/portal/index.html`，源码见 `deploy/portal/index.html`）右上角是一个自包含的账号控件：

- 未登录：`登录 / 注册` 按钮 → 弹出模态框（登录 / 注册两个页签，注册会按需显示邀请码字段）；
- 已登录：`👤 用户名`（管理员多一个金色标记）+ `退出`；
- 「日程表」卡片未登录时打「需登录」角标，登录后变成「已登录 · 可访问」；
- 注册成功会**直接跳进 `/schedule/`**，因为注册即建会话（Cookie 是同一个域，PWA 也能直接认）。

它调用的就是 `/schedule/api/auth/{session,register,login,logout}`，因此**没有任何独立的第二套账号**：
网站上注册的账号就是日程表里「设置 → 账号」看到的那个账号。站点其他项目不受影响（它们没有登录墙）。

同时它**在服务端被强制**，不是靠前端藏卡片：未登录访问 `/schedule/api/events` 一律 401。

替换门户时的注意事项（踩过的坑）：

- CSS 里一定要有 `[hidden] { display: none !important; }` —— 否则 `.account { display: flex }`
  会盖掉 `hidden` 属性（作者样式优先于浏览器默认样式），账号按钮会在会话还没拿到时就亮出来；
- 门户与 `index.html.bak.*` 都在 `/var/www/portal/`，回滚只需把备份覆盖回去。

### 前端构建参数

| 变量 | 作用 | 本机开发 | nzlab 线上 |
| --- | --- | --- | --- |
| `VITE_BASE` | 静态资源与路由前缀，写进 `index.html` 与 SW 作用域 | `/`（默认） | `/schedule/` |
| `VITE_API_BASE` | 覆盖 API 前缀（留空则用 `VITE_BASE + api`） | 留空 | 留空 |

> 忘了改 `VITE_BASE` 就会出现「页面能开但白屏」：HTML 里引用的是 `/assets/...`，而线上静态文件在 `/schedule/assets/`。

---

### 独立子域方案（可选）

若以后给 `schedule.nzlab.online` 单独签发证书，则改用 `deploy/nginx/schedule.nzlab.online.conf`
（独立 server 块、自带 HTTPS 配置），把 `PUBLIC_BASE_URL` 改成子域，前端用 `VITE_BASE=/` 重新构建即可。

---

## 7. 同步引擎行为

1. 每个连接器独立抓取（`httpx` + 指数退避 + 抖动 + 超时，401 时刷新令牌重试一次），
   单个连接器失败只影响它自己，`/api/status` 会标 `degraded` 并给出原因。
2. 写入时以 `id = hash(source + source_id)` **upsert**：外部字段（标题/时间/地点/描述）会被更新，
   **本地状态（`status`）永不覆盖** —— 你在 App 里打的勾不会被下一次同步抹掉。
3. 清理：超过 `EVENT_RETENTION_DAYS`（默认 30 天）的旧事件删除，`source=custom` 的手动事件保留。
4. 时间一律以 **UTC** 入库，出入接口按 `Asia/Shanghai` 呈现；前端用上海时区的日期工具，
   所以手机时区错乱也不会串行。

---

## 8. 排障

| 现象 | 处理 |
| --- | --- |
| 打开 `/schedule/` 白屏但 `index.html` 200 | 前端不是用 `VITE_BASE=/schedule/` 构建的（HTML 里在找 `/assets/…`） |
| 一直显示登录页 | 正常：未登录时数据接口返回 401 才会出现登录墙；用邀请码注册或让管理员在「设置 → 账号 → 成员」里加人 |
| 注册报「邀请码不正确」 | `.env` 里的 `REGISTRATION_INVITE_CODE`；改完 `systemctl restart campushub-sync` |
| 想看现在有哪些账号 | `sqlite3 /var/www/schedule/data/campushub.db 'select id,username,role,is_active from users'`（或用管理员账号调 `GET /api/auth/users`） |
| 忘记管理员密码 | 用 `venv/bin/python` 打开库把该行 `role='admin'` 重置，或直接删掉账号重新注册第一个（第一个注册的即管理员） |
| 打开页面空白 / 一直转圈（无账号系统的老部署） | 查看 `/api/status`；多半是没带令牌 → 用 `?token=<ADMIN_TOKEN>` 打开一次 |
| 401 invalid token | 令牌与 `.env` 不一致（改了 `.env` 记得 `systemctl restart campushub-sync`） |
| 日历订阅 403 | `.ics` 地址里的 `token` 是 `SUBSCRIBE_TOKEN`，不是 `ADMIN_TOKEN` |
| 微软连接器 `reauthorize_required` | 重新走一次设备代码登录；公司策略可能要求重新同意权限 |
| 课表为空 | `TJU_MODE` 是否正确；微北洋令牌过期时用 ICS 上传兜底 |
| PWA 更新不生效 | 确认 Nginx 对 `sw.js` 发了 `no-cache`；或在设置里“强制刷新” |
| 时间显示差 8 小时 | 检查 `PUBLIC_BASE_URL`/容器时区；数据层是 UTC，展示层是上海 |

---

## 9. 安全须知

- **两种凭据职责分离**：`SUBSCRIBE_TOKEN` 只读，泄露后最多暴露日程内容，最坏情况是**换掉它并重新订阅**；
  `ADMIN_TOKEN` 泄露等于交出全部数据 —— 立刻更换并检查 `/api/logs`。此外还有**账号会话**：普通成员只能读，
  管理员账号可以写，等价于 `ADMIN_TOKEN`（但可以随时停用、改密码）。
- **注册默认需要邀请码**（`REGISTRATION_INVITE_CODE`）：不设邀请码又不打开 `ALLOW_OPEN_REGISTRATION` 时，
  注册整体关闭（`/api/auth/session` 里 `registration_open=false`，App 与门户都会隐藏注册入口）。
  **第一个注册的账号自动成为管理员**，所以请自己先注册，别把邀请码公开。
- 会话 Cookie 是 `HttpOnly` + `SameSite=Lax` +（HTTPS 下）`Secure`，脚本读不到；签名密钥在
  `data/session.secret`（0600）—— **备份 data 目录就等于备份了所有人的登录态**，别外传。
- 登录失败有内存限流（默认 10 分钟内 8 次，按 用户名+IP），注册/登录接口都做了 400/401/403 的语义区分，
  不会泄露「账号是否存在」以外的信息（口令校验对不存在的账号也走一次哈希，避免时间侧信道）。
- **凭据加密（Fernet）**：替用户保管的密钥 —— 教务系统密码、微北洋 token、微软 `refresh_token`、
  注册邀请码 —— 在 `kv` 表里以 `enc1:<keyid>:<token>` 形态存放（AES-128-CBC + HMAC-SHA256，
  密钥 = HKDF-SHA256(`CREDENTIAL_KEY`)；未设则生成 `data/credential.key`，0600，与会话密钥分开，
  轮换会话不会连坐凭据）。`tools/encrypt_kv_secrets.py` 负责迁移与巡检：`--dry-run` 只看不改，
  `--check` 发现残留明文时退出码 1（可挂监控）。只加密还不够 —— SQLite 的 UPDATE 会把旧明文留在空闲页
  和 WAL 里（实测迁移后 db 里有 2 处、WAL 里 16 处 `"password":` 字面量），服务器上跑一次
  `deploy/purge-plaintext-residue.sh`（VACUUM + 截断 WAL + 完整性/行数/日志自检），实测整理后 0/0。
  **密钥要备份且不要改**：改了或丢了，日志出现 `key mismatch`，所有已存凭据打不开（表现为「未绑定」，
  不会 500），用户重新填一次即可恢复。
- **登录口令是单向哈希**（PBKDF2-SHA256 / 260k 轮 + 每用户随机盐，见 `accounts.py`），**刻意不可解密** ——
  能解密的口令迟早会泄露；只有「要拿去登别人系统」的凭据才需要加密。
- `data/` 目录含微软 `refresh_token`（已加密）与 `credential.key`/`session.secret` 两个密钥文件：
  **备份 data 目录 = 备份了密钥本身**，别外传；`.gitignore`/`.dockerignore` 已排除整个 `data/`。
- 服务只监听 `127.0.0.1`，外网仅经 Nginx + TLS 暴露；`/schedule/api/` 是唯一入口。
- 前端仍支持「我有访问令牌」的只读模式（`localStorage` 存令牌，共用设备上可在设置里清除）——
  这是给不方便注册的设备的兜底，不是主路径。
