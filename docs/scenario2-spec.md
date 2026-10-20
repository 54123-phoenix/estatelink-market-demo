# 场景二实施规格

基线 main 745085d，本地分支 codex/scenario2-archives。保留 Python 标准库 HTTP 和原生 HTML/CSS/JS；不引入 FastAPI/Vue。远端提交按用户授权执行；不自动合并到主分支或删除分支。

## 交付
- 管理员录入客户及资产、合同元数据，自动保存 SQLite；手机端展示脱敏档案，身份切换仍是演示不是登录。
- 服务仅监听 127.0.0.1:3000。全部资料为虚构演示。单客户一个主账号，多项资产。合同不上传、不签署。
- SQLite 表 users/assets/contracts/inquiries/market_flows/market_profile_links/audit_logs/app_meta；外键、WAL、每请求独立连接、事务写入。数据库唯一来源，无长期内存客户副本。
- users 保留原整数 ID 和状态；assets 一个 account 主账号（唯一约束），item 关联主账号；主账号保存 game/platform/account，兼容用户响应投影。无删除功能。
- 姓名、电话、身份证、邮箱、地址、紧急联系人、账号用 Fernet 加密。环境变量 ESTATELINK_DATA_KEY 必需，缺失或错误拒绝启动；独立派生 HMAC 指纹用于身份证重复检测。所有 GET 返回脱敏字段，不返回游戏密码。日志不含敏感信息。
- 密钥和 SQLite/WAL/SHM 不提交。允许 ESTATELINK_DB_PATH 指定测试隔离路径。提供 generate_key.py 和 requirements.txt。
- 首次导入旧 data.json（存在而损坏则失败，不能回退默认）或 12 位示例；保留 ID/状态/未回应次数。旧 JSON 保留但不再写。导入原 market_state.json 或原初始化进度；导入两例道具并建立固定行情链接。迁移事务与版本标记防重复。
- 改账号不丢行情：overview 返回 catalog.profiles 改为按 str(userId) 索引，前端原按 account 的读取全部调整。行情配置文件无需改。新资产没有行情，不套价。现有核验状态迁移语义不改。

## API
- 保留 /api/users/add POST（创建客户+主账号，返回 ok/userId）、/api/users GET（now/users/autoSend）、/api/mobile/users GET、/api/mobile/messages GET、/api/mobile/reply POST、/api/sms/send POST、/api/users/confirm-dead POST、/api/auto-send POST、/api/market/overview GET、/api/market/flow POST。
- /api/save POST 兼容返回 ok/userCount/message，说明自动保存，不写 JSON。
- GET/PATCH /api/archive/users/{id}；GET/POST /api/archive/users/{id}/assets；PATCH /api/archive/assets/{id}；GET/POST /api/archive/users/{id}/contracts；PATCH /api/archive/contracts/{id}。
- 档案 GET 用户直接返回脱敏对象，assets 返回 {assets:[...]}, contracts 返回 {contracts:[...]}。写接口返回 {ok:true,userId/assetId/contractId}。
- 用户字段 name/phone/idCard/email/address/emergencyContact/gender/age，创建另需 game/account，可选 platform。创建必填 name/phone/game/account。
- 资产字段 assetType/platform/game/name/account/quantity/costMinor/currency/acquiredAt/disposition/notes/parentAccountId；account 不允许通过新增资产重复创建；POST 默认 item，parentAccountId 服务端关联。PATCH 不变更归属或类型。
- 合同字段 number/name/status/effectiveDate/expiryDate。number 全局唯一；status draft/active/terminated。
- camelCase；错误 {error:"说明"}，400/404/409/500。字段白名单，拒绝 status/missedCount 越权字段。未提交保持原值，可选字段空值清除。姓名/名称<=100，账号<=128，备注/地址<=500；数量正整数、成本整数>=0（总成本分）、币种三位大写；日期 YYYY-MM-DD、到期>=生效。phone 11位 ASCII数字允许100虚构号，idCard可选但填写18位；age可选1..150。
- 敏感字段返回脱敏（姓名首字、电话前三后四、证件末四、账号部分、地址/紧急联系人部分）；编辑敏感框不预填脱敏值，空框省略更新，清除可选字段用明确按钮。

## 页面
- 后台客户池保留核验和行情，新增管理档案入口 /archive-admin?userId=N；移除密码列/输入。新增客户后进入档案。
- 档案页基本资料、主账号与资产、合同三个区域，表单可新增编辑、错误保留输入、提交禁用、防重复，保存后重读显示更新时间。
- 手机 page-assets 替换占位，显示脱敏信息/资产/合同；支持 tab=assets。身份切换立即清空，用请求序号防串档。仅可见时每5秒刷新，支持手动刷新。无效 userId 提示而非旧身份内容。
- 我的：资料摘要+新增演示客户按钮，注册去除游戏密码，注册后选新客户进入 assets。
- 继续现有配色和样式，无框架。所有动态用户输入使用 textContent 或可靠转义，避免内联 onclick 拼用户字符串。明确显示“演示身份，不代表真实访问授权”、模拟报价和合同登记状态。

## 验证
- unittest 临时数据库/密钥：单主账号、资产归属、事务回滚、重复证件合同、校验、编辑保留/清除、重启持久化、密文/响应不泄露、迁移幂等/损坏失败、并发核验新增、行情关联和原处置流程。
- 浏览器后台创建客户+2资产+合同，手机同步，修改刷新，快速切换、390宽响应式、XSS文本、重启、核验及行情回归。
- 交付 README、API/迁移/密钥文档、演示步骤、QA记录；不上传个人资料、密钥或运行数据库。
