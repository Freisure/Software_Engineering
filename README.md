# 书循环 · 校园二手教材流转平台

按课程代码找教材，在线预约，线下交接。面向软件工程课程实践的完整 B/S 应用，包含学生端、管理端、持久化数据库与自动化测试。

## 快速运行

要求 Python 3.12 或更高版本。Windows 双击 `start.bat`，然后访问 **http://127.0.0.1:5000**。首次启动自动安装依赖并初始化演示数据；之后数据持续保存在 `instance/`，不会重置。

跨平台手动运行：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
# Windows PowerShell:
$env:CAMPUS_DEMO="1"
# macOS/Linux: export CAMPUS_DEMO=1
python app.py
```

| 演示角色 | 学号 | 密码 |
|---|---|---|
| 发布者（林同学） | `20240001` | `Campus2026!` |
| 需求者（陈同学） | `20240002` | `Campus2026!` |
| 学院管理员 | `admin` | `Campus2026!` |

演示账号、联系方式与教材封面均为虚构。仅当显式开启 `CAMPUS_DEMO=1` 且数据库无用户时创建；正式部署不启用演示模式，单独创建管理员。

## 已实现功能

- 学号注册、登录、修改密码、个人资料、角色权限与会话失效机制。
- 1—3张教材图片上传、格式与大小校验、发布审核、驳回理由、编辑重审与下架。
- 按课程代码模糊匹配、教材名与课程名搜索，学院/课程/成色/价格/免费组合筛选与排序。
- 一个教材一个有效预约，发布者接受或拒绝，交接状态机、双方确认、取消记录、超时申诉与管理员裁定。
- 预约接受后联系方式仅对交易双方显示；三维评分、标签与评价删除。
- 信用分结算、低信用限制、举报处理、处罚复核与一次性恢复信用分。
- 管理统计、学院与日期筛选、CSV导出、课程CSV导入、规则配置、通知与操作日志。
- SQLite事务、部分唯一索引保证并发预约一致性；备份与超时维护命令。

不包含支付、物流、跨校交易、实时聊天和统一身份认证对接。统一认证仅预留 `sso_id` 字段。

## 演示顺序

1. `20240001` 登录 → 发布教材并上传真实图片 → 我的书架查看“待审核”。
2. `admin` 登录 → 管理中心 / 教材审核 → 通过或驳回。
3. `20240002` 登录 → 输入 `SE3` → 查看教材 → 预约未来时间和校内地点。
4. `20240001` 登录 → 我的预约 → 接受预约 → 开始交接 → 确认已交接。
5. `20240002` 登录 → 我的预约 → 确认已交接 → 评价对方。
6. 双方信用各增加2分；管理员查看统计与操作日志。
7. 异常演示：预约接受后申诉 → 管理员裁定；教材举报 → 管理员处理 → 被处罚者在个人中心申请撤销处罚 → 管理员复核。

请使用两个浏览器窗口或退出后切换账号。同一浏览器的普通标签页共享登录状态。

## 项目结构

```text
app.py                  Flask接口、权限、业务事务与状态机
schema.sql              数据库结构与约束
seed.py                 显式演示模式的数据与自制封面
manage.py               管理员创建、备份、超时维护
static/                 中文响应式页面、样式、原生JavaScript
tests/                  业务集成与维护测试
docs/                   需求、设计、测试、部署与AI协作记录
.github/workflows/      GitHub Actions自动测试
start.bat               Windows启动入口
instance/               运行时数据库、图片、会话密钥（不上传Git）
```

## 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check static/app.js
```

测试使用隔离临时数据库，不修改演示数据。详见 [测试报告](docs/testing.md)。

## 维护与部署

```bash
# 正式环境先关闭 CAMPUS_DEMO，再执行：
python manage.py create-admin admin2026 --name 学院管理员
# 密码交互输入，不出现在命令参数中。
python manage.py backup
python manage.py expire
```

备份保存在 `backups/日期时间/`，含一致性数据库快照与上传图片。每日备份可由 Windows 任务计划程序或 cron 调用；超时规则在预约页面访问时执行，也可每小时调用 `expire`。项目不会自行修改系统任务计划。

默认使用 Waitress，仅监听本机。校内服务器部署、HTTPS、备份恢复、数据口径和限制见 [部署说明](docs/deployment.md)。

## 软件工程资料

- [需求与验收矩阵](docs/requirements.md)
- [系统设计与数据库](docs/design.md)
- [测试记录](docs/testing.md)
- [部署与用户手册](docs/deployment.md)
- [AI协作记录与待人工核实项](docs/ai-collaboration.md)

该项目可作为课程实践实现和报告素材；用户访谈、学校实际课程代码、教师要求与线上环境验收仍需人工核实，未虚构完成记录。
