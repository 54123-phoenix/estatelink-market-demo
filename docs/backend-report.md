# 后端实施与验证报告

## 模块与运行接口

- `demo/server.py`：标准库 `ThreadingHTTPServer`，`make_server(host='127.0.0.1', port=3000, *, db_path=None, key=None, base_dir=None)` 可测试工厂。仅允许 loopback；导入模块或创建服务器不启动后台线程。`main()` 才启动核验超时和轮询发送任务。
- `demo/storage.py`：`Store` 每次操作独立 SQLite 连接，启用外键与 WAL，写操作 `BEGIN IMMEDIATE`，异常回滚。规格所列八张表持久化唯一运行状态，无长期内存客户副本。
- `demo/fixtures.py`：原12位虚构客户迁移 fixture，移除所有游戏密码。
- `generate_key.py`：生成 Fernet 密钥；`requirements.txt` 声明 cryptography。必需 `ESTATELINK_DATA_KEY`，可选 `ESTATELINK_DB_PATH`。新数据库和已有数据库均拒绝缺失/错误密钥；已有数据库启动也校验实际敏感密文。
- 用户姓名/电话/证件/邮箱/地址/紧急联系人与资产账号分别加密，证件另用独立派生 HMAC 唯一指纹；核验短信正文亦加密保存。日志不输出客户资料和请求体。

## 实际 API 形状

- `GET /api/archive/users/{id}` 直接返回用户对象：`id,name,phone,idCard,email,address,emergencyContact,gender,age,status,missedCount,game,platform,account,mainAccountId,createdAt,updatedAt`。敏感值均脱敏，空可选字段为 null，无密码字段。
- `GET /api/archive/users/{id}/assets` 返回 `{assets:[...]}`：`id,userId,assetType,parentAccountId,platform,game,name,account,quantity,costMinor,currency,acquiredAt,disposition,notes,createdAt,updatedAt,hasMarket`。账号脱敏，主账号唯一且数量1；道具自动关联主账号。`hasMarket` 只对实际固定行情链接代表资产为 true。
- `GET /api/archive/users/{id}/contracts` 返回 `{contracts:[...]}`：`id,userId,number,name,status,effectiveDate,expiryDate,createdAt,updatedAt`。合同编号全局唯一。
- 创建客户 `POST /api/users/add` 返回 `{ok:true,userId}`；档案 PATCH 用户、POST/PATCH 资产、POST/PATCH 合同分别返回 `{ok:true,userId}`、`{ok:true,assetId}`、`{ok:true,contractId}`。
- 客户创建必需 `name,phone,game,account`。PATCH 不提交的字段保持原值，可选字段 null/空文本清除；字段白名单拒绝越权改核验状态/次数/归属/类型。`currency` 默认为 CNY，提交时须有效三位大写字母；成本未提供为 null（未知总成本分）。主账号与道具默认 `quantity=1,disposition='inherit'`。处置意愿支持 `inherit/sell_then_inherit/donate/memorial_close`，合同支持 `draft/active/terminated`。
- 原 `/api/users`、`/api/mobile/users`、`/api/mobile/messages`、`/api/mobile/reply`、`/api/sms/send`、`/api/users/confirm-dead`、`/api/auto-send`、`/api/market/overview`、`/api/market/flow` 均保留。`/api/users` 仍为 `now/users/autoSend`；所有用户投影脱敏。`POST /api/save` 返回 `{ok:true,userCount,message}`，提示自动保存，不写 JSON。
- 行情 overview 的 `catalog.profiles` 按字符串用户 ID 索引，原 `flows` 的 `userId:assetType` 键不变。固定资产链接不依赖编辑后的账号，新资产没有报价或行情流程。原处置状态机和核验状态含义保留。
- 错误统一为 `{error:'说明'}`，400/404/409/500；内部异常不向响应回显 SQL 或敏感值。

## 迁移

首次初始化事务内导入 `data.json` 或专用 fixture，保留客户整数 ID、状态、未回应次数与下一 ID；忽略旧游戏密码。存在但损坏的旧文件导致启动失败，错误标识来源文件，事务内已写记录回滚。旧 JSON 不修改。存在 `market_state.json` 时导入版本和进度；不存在则导入原初始化进度。两例道具及固定行情链接同一事务建立。版本标记仅于成功后写入，重启不重复导入。

## 验证

命令（项目根目录）：

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

结果：14 tests，2.129秒，全部通过。每个用例使用临时数据库与临时随机密钥；未创建项目运行数据库或密钥文件。

覆盖：缺失/格式错误/不匹配密钥、密文损坏拒绝启动；单主账号、资产归属/类型不可修改；数据库唯一约束、事务回滚；重复证件/合同；字段边界/白名单/日期与到期顺序；PATCH 保留与清除；重启持久化、原始密文与 GET 脱敏；迁移 ID/状态/进度保留、幂等与损坏失败；并发发送只留一条 pending 以及同时新增和回复；连续3次超时、回复重置、人工确认；自动轮询游标重启；改账号保留行情、新资产无行情和原挂售/买家/决定/修改/重置流程；HTTP 错误码、档案 CRUD 实际端点与兼容保存响应；拒绝监听非 loopback。

## 范围与限制

后端没有未解决的规格阻塞项。浏览器验收、README 和用户文档由主代理负责。身份切换为演示，接口没有真实登录授权；短信与报价均为模拟，合同仅登记元数据。GET 自由短信正文按原功能返回，前端需作为文本渲染；不得将真实个人资料写入演示短信。

未执行提交、推送、合并、分支或工作树删除。
