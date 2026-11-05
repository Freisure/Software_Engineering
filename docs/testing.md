# 测试报告

日期：2026-11-05。环境：Windows、Python 3.12、Flask 3.1.3、SQLite、Waitress、Chrome浏览器。以下为实际执行记录，不代表目标校内服务器的最终验收。

## 自动化业务测试

`python -m pytest -q`：16组集成测试通过。测试针对真实Flask请求、隔离SQLite数据库和真实图片内容，不使用业务逻辑模拟。

| 测试 | 覆盖的行为 |
|---|---|
| account_validation_roles_password_and_csrf | 密码长度、学号重复、学生不能访问管理接口、原密码校验、CSRF |
| moderation_search_edit_and_upload_validation | 无效课程/价格/图片、图片真伪、审核可见性、编辑重审、课程筛选与脱敏 |
| handoff_privacy_exclusivity_reviews_credit_and_audit | 预约独占、参与人权限、非法跳转、联系方式隔离、双确认、信用与评价去重、统计日志 |
| cancel_report_appeal_and_admin_resolution | 取消次数、交接申诉、管理员爽约裁定、举报扣分与下架 |
| course_csv_config_profile_and_permissions | 课程CSV、低信用阈值、资料更新、管理员导出 |
| concurrent_reservation_one_winner | 两个真实并发请求，结果为201与409，只有一个有效预约 |
| timeout_is_audited_and_can_be_resolved_once | 单方确认超时、审计记录、管理员完成裁定与防重复加分 |
| import_rolls_back_all_rows_and_upload_ownership | 批量课程事务回滚、上传图片归属、非所有者禁止下架 |
| login_lockout_and_password_invalidates_other_sessions | 10次失败限流、密码变更后其他会话失效 |
| report_appeal_reverses_credit_only_once | 举报误罚复核、实际信用恢复、禁止重复恢复与申诉 |
| backup_produces_consistent_database_and_upload_copy | 备份完整性、用户数据与图片存在、密钥不入备份 |
| admin_provision_is_explicit_and_password_hashed | 显式管理员创建与密码哈希 |
| email_binding_requires_the_mailed_code | 邮箱格式、验证码错误被拒、绑定前不生效、绑定后仅返回脱敏邮箱 |
| password_reset_end_to_end | 未知学号不泄漏账号、一次性重置链接、重置后旧会话失效、旧密码不可登录、链接不可重放 |
| email_can_be_unbound_with_the_password | 错误密码拒绝解绑、解绑后邮箱清空、未绑定账号不再发送重置邮件 |
| account_deletion_releases_the_student_id | 错误密码拒绝注销、注销后会话失效、学号释放可重新注册、旧密码不可登录 |

开发时先对空接口运行核心测试，得到6组预期失败，再实现到通过。处罚复核和维护命令均先观察缺失行为导致的失败，再实现并运行完整测试。最终源码另执行JavaScript语法检查。

## 真实浏览器验收

Chrome中实际完成：

1. 需求者登录，搜索 `SE3`，匹配软件工程课程教材，并显示常用教材信息。
2. 打开教材详情，发起未来时间、图书馆地点的预约。
3. 发布者登录接受预约；接受前隐藏联系方式，接受后显示对方联系方式。
4. 发布者开始交接并确认，显示等待需求者确认。
5. 需求者确认，完成交易并评价；个人中心信用显示102。
6. 实际上传教材图片并提交，管理员审核通过，统计显示7本发布、1次完成交接。
7. 管理员统计、审核、交接申诉、举报处理、课程库、规则、日志页面可访问。
8. 390px手机宽度的教材集市与发布页检查，无页面横向溢出；检查截图后优化价格与筛选栏换行。
9. 浏览器控制台检查：未发现脚本错误。

浏览器测试使用独立的本机演示数据库，交付初始化不包含这些验收操作。后台业务完整性主要由集成测试覆盖，未声称每个按钮的每种输入都做了人工测试。

## 性能抽样

运行 `python tests/benchmark.py`，自动建立并清理隔离数据库：1000本教材，50个同时开始的HTTP课程搜索请求，查询 `SE3` 返回167条匹配教材。使用16个Waitress工作线程。

| 指标 | 本机抽样结果（秒） |
|---|---:|
| 成功请求 | 50 / 50 |
| P50 | 1.6434 |
| P95 | 1.8244 |
| 最大值 | 1.8323 |

本次抽样满足≤2秒目标。此结果仅覆盖本机回环网络的课程搜索JSON接口，不包括图片加载、弱网、50人同时上传或持续压力。目标服务器需在相同数据规模下复测；不把一次抽样表述为服务等级保证。

## 剩余验收工作

真实学生/管理员访谈、实际课程CSV核对、正式HTTPS代理配置、服务器备份恢复演练和校内网络压测需由项目使用者完成。功能边界见需求矩阵，未虚构这些人工工作已完成。
