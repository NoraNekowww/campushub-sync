# CampusHub Sync — 交接说明

> 统一日程/DDL 聚合器：把「微软 To Do 待办」和「天津大学课表」合成一条时间线，输出网页 PWA + `.ics` 订阅。
> 交接日期：2026-10-10 ｜ 代码仓库根目录：`campushub-sync/`（开发机 `E:\Alpha_nz_Files\campushub-sync`）

---

## 1. 线上在哪

| 项 | 值 |
| --- | --- |
| 应用地址 | **https://nzlab.online/schedule/** |
| 门户（导航主页，右上角是账号区） | https://nzlab.online/ |
| 服务器 | `nzlab.online` = `108.186.202.38`（laserver01-nz，Debian 12） |
| SSH | `ssh -i ~/.ssh/nzlab_rsa root@nzlab.online`（同一把私钥在开发机桌面 `AboutServer/.ssh/.ssh/id_rsa` 也有一份） |

## 2. 服务器上的结构

```
/var/www/schedule/            ← 全部东西都在这（约 126M）
├─ backend/app/               ← FastAPI 应用（改了它就要重启服务）
│  ├─ api/        端点：events sync status calendar accounts tju auth_ms schedule
│  ├─ connectors/ 数据源：ms_todo.py / tju_schedule.py / tju_api.py / demo.py
│  ├─ services/   sync_engine.py（同步编排）/ events.py / ics_export.py / scheduler.py
│  └─ models.py db.py config.py timeutil.py security.py accounts.py
├─ frontend/                  ← 已构建的前端（Vite 产物，nginx 直接发这个）
├─ data/                      ← 数据（chmod 700）
│  ├─ campushub.db            ← SQLite，**唯一的数据文件**，权限 600
│  ├─ campushub.db-wal        ← WAL 日志（备份时一起拷）
│  ├─ session.secret          ← 网页登录会话签名密钥
│  └─ ms_token.json           ← 微软令牌（接上 To Do 之后才会出现，600）
├─ .env                       ← **所有密钥都在这里**（权限 600，不在 git 里）
├─ venv/                      ← Python 虚拟环境
├─ deploy/ tools/ web/        ← 部署脚本 / 调试脚本 / 前端源码
└─ README.md                  ← 开发文档（含完整接口表、协议细节）
```

**服务**：systemd 单元 `campushub-sync`
- 启动：`/var/www/schedule/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --workers 1`
- 工作目录 `/var/www/schedule/backend`，环境变量取自 `/var/www/schedule/.env`
- 只监听 `127.0.0.1:8010`，**只由 nginx 反代对外**（同机 8000 是另一个项目 cycle，别动）

**nginx**：单站点配置 `/etc/nginx/sites-available/default`（只监听 443），
`/schedule/` 这一段是 `include /etc/nginx/snippets/campushub-sync.conf;`（由 `deploy/install.sh` 插入，在 default 文件第 ~99 行）。
改完先 `nginx -t` 再 `systemctl reload nginx`。

## 3. 钥匙（`.env` 里三条 + `data/` 里两个密钥文件）

| 变量 | 用途 | 怎么用 |
| --- | --- | --- |
| `ADMIN_TOKEN` | 机器令牌，给脚本/调试用 | 请求头 `X-Admin-Token: <值>`，可读写 |
| `SUBSCRIBE_TOKEN` | **日历订阅**专用只读令牌 | 订阅地址：`https://nzlab.online/schedule/api/subscribe/calendar.ics?token=<值>` |
| 网页账号（`nzs`，admin） | 人用 | 打开 `/schedule/` 登录；口令存在 `data/campushub.db`，pbkdf2 加盐，会话是 HttpOnly Cookie |
| `REGISTRATION_INVITE_CODE` | 注册邀请码（门户右上角注册要填） | — |
| `CREDENTIAL_KEY`（留空则用生成的 `data/credential.key`） | **加密存储**的凭据：教务密码、微北洋 token、微软 refresh_token、邀请码 | **别改、要备份** —— 改了或丢了，日志出现 `key mismatch`，所有人已存的凭据都打不开，得重填一次 |

泄漏/换人时的处理：直接改 `.env` 里对应值 → `systemctl restart campushub-sync`（订阅那串会变，要通知订阅者换）。

另外两个密钥文件是**自动生成**、不在 `.env` 里：`data/session.secret`（会话签名）、`data/credential.key`（凭据加密，0600）。
备份 `data/` 时两个都要带上；**轮换 `SESSION_SECRET` 只影响登录态，轮换 `CREDENTIAL_KEY` 会作废已存凭据**（这是刻意分开的）。

## 4. 日常运维

```bash
systemctl status campushub-sync          # 看活着没
systemctl restart campushub-sync         # 重启（改后端 / 改 .env 后）
journalctl -u campushub-sync -n 100 -f   # 看日志
curl -s -H "X-Admin-Token: $T" http://127.0.0.1:8010/api/status   # 健康 + 最后一次同步结果
# 凭据加密巡检（0 = 没有残留明文）：
cd /var/www/schedule/backend && DATA_DIR=/var/www/schedule/data /var/www/schedule/venv/bin/python - --check < /var/www/schedule/tools/encrypt_kv_secrets.py
```

**发版（幂等，可反复跑）**：

```bash
# ① 开发机：只改了前端才需要先构建（**最容易忘的一步**，漏了就是白屏/旧页面）
cd web && VITE_BASE=/schedule/ npm run build && cd ..     # 产物在 web/dist/

# ② 打包后端与部署脚本，上传
tar czf rel.tar.gz backend deploy tools README.md web/src
scp rel.tar.gz root@nzlab.online:/tmp/

# ③ 只改了前端时，另把产物覆盖上去（install.sh 不管前端）
scp -r web/dist/* root@nzlab.online:/var/www/schedule/frontend/

# ④ 服务器：解包 + 安装。install.sh 会更新 venv、装 systemd 单元、装 nginx snippet、重启服务，
#    且**从不覆盖已有 .env**（密钥安全），nginx include 已存在时不会重复插
ssh root@nzlab.online 'cd /var/www/schedule && tar xzf /tmp/rel.tar.gz && bash deploy/install.sh && rm -f /tmp/rel.tar.gz'
```
> 子路径部署必须带 `VITE_BASE=/schedule/`，否则打包出来的资源路径是 `/assets/...`，页面白屏。

**备份**：只需备份 `/var/www/schedule/.env` 和 `data/`（`campushub.db*` + `session.secret` + `ms_token.json`）。建议停服务后再拷 DB，或连 WAL 一起拷。

## 5. 数据从哪来 / 现在接到哪一步

| 数据源 | 状态 | 说明 |
| --- | --- | --- |
| **微软 To Do** | ⚠️ **未接**（缺 `MS_CLIENT_ID`） | 需去 Azure 建一个应用注册拿客户端 ID 填进 `.env`；登录走设备代码流（`microsoft.com/devicelogin`）。令牌落在 `data/ms_token.json`，自动刷新，坏了会回报 `reauthorize_required` |
| **天大课表（微北洋）** | ⚠️ **未导入**，当前跑演示数据 | 见下面第 6 节，**必须在校园网内的浏览器里抓一次** |
| `TJU_MODE=demo` | ← 线上现在是这个 | 打开就有 16 条带「（演示）」的事件（6 条 DDL + 10 节课），用来验证链路 |

**当前线上实况**：服务正常、调度器每 20 分钟跑一次且无报错，但数据仍是演示数据（16 条）。**交接后的第一件事就是让真数据进来。**

## 6. 天大课表的硬限制（重要，别再重新踩一遍）

- `open.twt.edu.cn`（课表/考试接口）**只对校园网开放**：校外请求 → `302 → network-notice.tju.edu.cn`，拦截页原文「该网页目前只允许校内访问或您正在进行违规操作」。**服务器在境外，永远拉不到**，这不是配置问题。
- 登录本身服务器能通：`POST api.twt.edu.cn/api/auth/common`，但要带官方客户端的 `ticket` + `domain: weipeiyang.twt.edu.cn` 两个头（少了就是 `50003 未绑定的url`）。
- 签名算法、接口地址、返回结构（`Classtable{termStart, courses[{coursename,teacher,week{start,end},arrange[{day,start,end,week,room}]}]}`、`单双周` 语义）已全部逆出并实测，写在 **`README.md §4.2`** 和 `backend/app/connectors/tju_api.py`（有测试样本）。
- 教务系统（`classes.tju.edu.cn/eams`，认证走统一身份认证 `sso.tju.edu.cn` 的 CAS）**公网可达**，不需要校园网：
  服务器（洛杉矶）实测**能登录并抓到课表** —— 2026-10-10 用已存凭据导入 11 门课 / 14 时段 → 132 个事件
  （week 6、`term_start` 2026-08-31 全对）。CAS 登录带图形验证码，服务器送 `learning.twt.edu.cn/ocr` 识别，
  认不出来才让用户手填一张。**这条链路是主路径**：`backend/app/connectors/tju_cas.py` + `api/tju.py`，
  前端「设置 → 课表导入」输学号 + 教务密码即可（早期 HANDOVER 里「教务在校园网内、脚本登录不可靠」的说法已证伪）。

**主路径 = 服务器端 CAS 直连**（上面那条），微北洋 `open.twt.edu.cn` 降为「高级」里的兜底：它是浏览器跨站请求，
会被 CORS 拦（在校园网里也一样），且接口只对校园网开放 —— 这就是「连着天大 WiFi 仍提示连不上」的真正原因。
被 CORS 拦时面板会给出「手动兜底」的链接和一段控制台命令；服务器侧「让服务器试着抓」按钮不在校园网时会明确回
`campus_network`，不会假装成功。

**开学必做**：设置 → 课表导入 → 填学号 + 教务密码 → 一键导入。成功后学期第一周周一按接口返回的 `term_start`
自动校正，演示数据自动清掉，同步引擎自动重建，**不用改 `.env` 也不用重启**。

## 7. 改完代码怎么验

```bash
# 后端测试（本机）
cd campushub-sync && .venv/Scripts/python.exe -m pytest backend -q
#   预期：全绿（106 项）。tests/conftest.py 里两件事让旧用例重新跑得动：
#     ① CAPTCHA_ENABLED=false —— 注册用例不该去认 SVG 里的字；
#     ② admin_headers 懒建一个 owner 账号 —— 时间线按账号隔离后，共享管理员令牌
#        只有 owner 存在时才解析得出身份（别改成全局 autouse：注册那几个用例要靠
#        「第一个账号是它自己建的」）。

# 线上端到端检查（在开发机跑，会开 headless Edge；账号临时建、跑完删）
cd tools/visual && node verify-tju-panel.mjs      # 线上设置页 + 微北洋面板 + 无控制台报错
node verify-ui.mjs / verify-auth.mjs / verify-portal.mjs
cd web && USERNAME_E2E=e2echeck PASSWORD_E2E=... node tools/verify-swipe-delete.mjs
#   ↑ 逐条断言「拖开 → 删除按钮真的露出来（命中测试）→ 点删除 → 卡片消失 + 服务端 hidden=true
#     → 提示条带撤销 → 点撤销 → 卡片回来」，顺带回归「点划掉还能用」
bash deploy/verify-tju-live.sh                    # 线上接口连通性
```

## 8. 已知遗留 / 下一步

1. **接微软 To Do**：Azure 应用注册 → 拿客户端 ID 写 `MS_CLIENT_ID` → 关 `DEMO_MODE` → 重启 → 网页里设备代码登录。（也可以改成「粘贴 refresh_token」的免 Azure 方案，还没做）
2. **课表首次导入**（见第 6 节）：设置 → 课表导入 → 学号 + 教务密码 → 一键导入，**不需要校园网**。
3. `.env` 里的 `MS_CLIENT_SECRET` 有值但**用不上**（公共客户端流不需要），确认没用可以清空。
4. 线上 `frontend_old/` 是旧构建残留，`Dockerfile`/`docker-compose.yml` 是早期产物（服务器内存太小，最终用 venv + systemd，没用 Docker），都可删。
5. 演示数据切换与账号/权限的边界情况：`TJU_MODE=demo` 是**独占**的，不接真数据时不要同时开 `DEMO_MODE`。
6. **凭据已加密**（2026-10-10）：`kv` 表里替用户保管的凭据（教务密码、微北洋 token、微软 refresh_token、邀请码）
   现为 `enc1:<keyid>:<Fernet token>`；密钥是 `data/credential.key`（0600，会自动生成）—— **跟数据库一起备份，
   不要改**，改了日志会出现 `key mismatch`，已存凭据要用户重填。巡检：
   `tools/encrypt_kv_secrets.py --check`。
7. **右滑删除 + 划掉/删除不进系统日历**（2026-10-11 已上线）：`Event.hidden` 软删除；
   卡片左右拖开露出「删除」，提示条带「撤销」。订阅 feed 默认只发站长自己的、且剔除
   `completed`/`hidden`，另发 `STATUS:CANCELLED` 墓碑。线上自检（会挑一条自己的日程删掉再撤销，
   数据原样）：`ssh host 'cd /var/www/schedule && venv/bin/python -' < tools/check-feed-hide.py`。
   **注意**：`X-CANCELLED-COUNT` 不该长期上涨 —— 涨了说明有东西被反复划掉/删掉。
8. 可选：现在卡片文案写明「密码存在服务器（已加密）」，如要做更高隐私，可加「不保存密码、每次刷新输一次」模式。
9. 注册闸门：`ALLOW_OPEN_REGISTRATION` / `REGISTRATION_INVITE_CODE` 控制门户能不能自助注册；用户管理在 `/api/auth/users`（`nzs` 是 admin）。
