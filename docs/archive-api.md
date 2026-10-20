# 场景二接口约定

仅用于本机虚构资料演示，没有登录鉴权。`userId` 只选择演示身份，不能证明访问资格。JSON 使用 camelCase，写入成功在事务提交后返回；错误统一 `{error:"说明"}`，400 输入错误、404 不存在、409 冲突、500 内部错误。

## 客户

`POST /api/users/add` 在同一事务创建客户和一个主账号，返回 `{ok:true,userId}`。必填 `name,phone,game,account`；选填 `platform,gender,age,idCard,email,address,emergencyContact`。

```json
{"name":"虚构客户","phone":"10000009001","game":"CS2","account":"fictional-demo-01","platform":"Steam"}
```

`GET /api/archive/users/{id}` 直接返回 `id,name,phone,idCard,email,address,emergencyContact,gender,age,status,missedCount,game,platform,account,mainAccountId,createdAt,updatedAt`。敏感字段均脱敏，不提供明文读取接口。

`PATCH /api/archive/users/{id}` 接受 `name,phone,idCard,email,address,emergencyContact,gender,age`，返回 `{ok:true,userId}`。未提交字段保留，可选字段 null 或空文本清除；姓名电话不能清空。游戏账号经主账号资产 PATCH 修改。拒绝密码、核验状态等白名单外字段。

## 资产

`GET /api/archive/users/{id}/assets` 返回 `{assets:[...]}`。

| 字段 | 含义 |
|---|---|
| id/userId | 资产与客户整数 ID |
| assetType/parentAccountId | account 主账号或 item 道具；道具关联主账号 |
| platform/game/name/account | 平台、游戏、名称、脱敏账号标识 |
| quantity | 正整数，主账号固定 1 |
| costMinor/currency | 整条资产的取得总成本，整数分；可空表示未知，币种默认 CNY |
| acquiredAt | 取得日期或 null |
| disposition | inherit、sell_then_inherit、donate、memorial_close；默认 inherit，可清空 |
| notes | 备注或 null |
| createdAt/updatedAt | Unix 毫秒时间戳 |
| hasMarket | 是否关联原有模拟行情代表资产，不表示实时估值 |

`POST /api/archive/users/{id}/assets` 添加道具，自动关联主账号，返回 `{ok:true,assetId}`。必填 name；选填 platform/game/account/quantity/costMinor/currency/acquiredAt/disposition/notes。数量默认 1，新资产暂无行情。

```json
{"name":"虚构饰品 A","platform":"Steam","game":"CS2","quantity":2,"costMinor":12345,"currency":"CNY","disposition":"inherit"}
```

`PATCH /api/archive/assets/{id}` 更新业务字段，返回 `{ok:true,assetId}`；不得修改 userId/assetType/parentAccountId。主账号的游戏、名称、账号不能清空，数量固定 1。修改账号文本不改变既有行情与处置关联。

## 合同

`GET /api/archive/users/{id}/contracts` 返回 `{contracts:[...]}`。

`POST /api/archive/users/{id}/contracts`、`PATCH /api/archive/contracts/{id}` 接受 `number,name,status,effectiveDate,expiryDate`，返回 `{ok:true,contractId}`。编号全局唯一，名称必填，status 为 draft/active/terminated（默认 draft）。日期可空；响应另有 id/userId/createdAt/updatedAt。不提供上传或签署。

## 校验与兼容

- 电话为11位 ASCII 数字，允许虚构100号段；证件可选，填写为18位数字或末位X，大小写规范化后以 HMAC 去重，不验证真实身份。
- 姓名/名称<=100字，账号<=128字，地址/紧急联系人/备注<=500字；年龄1–150或空。数量和成本为整数，成本非负；币种为三位大写字母。
- 日期 YYYY-MM-DD，到期不早于生效。取得成本不等于行情估值。
- `/api/users` 保留 now/users/autoSend、核验计时和状态字段；`/api/mobile/users` 保留身份列表，敏感字段脱敏且无 password。
- `/api/market/overview` 保留 users/catalog/flows/revision/asOf；catalog.profiles 以字符串客户ID索引，前端用 `profiles[String(user.id)]`。流程键继续 userId:account 或 userId:item。
- `/api/market/flow` 与原短信发送、回复、人工确认、自动发送接口保留。新资产不会增加交易方案。
- `POST /api/save` 返回 ok/userCount/message，提示已自动保存，不写旧JSON。
- 无删除接口。写入失败回滚，不留下半条客户或孤立资产。
