# 经验复盘：MCP OAuth 联合改造

> 覆盖 2026-10-05 ～ 10-06 从「静态 token」到「自建 IdP + OAuth-only」的全过程。按主题记录坑、根因与可复用教训。面向后续迭代者与复现者。

## 一、集成平台侧（CodeBuddy/WorkBuddy 开放平台）

1. **官方提示词模板的端点不可尽信**。模板写 `www.codebuddy.cn/oauth2`，实际落到企业登录页报"账号不存在"；真实可用是 `https://copilot.tencent.com/oauth2/*`（Keycloak）。教训：任何文档端点先 curl 实证再写代码。
2. **平台不允许 `localhost` 回调，`127.0.0.1` 可以**。一字之差卡一小时。
3. **"SMS 登录故障"实为浏览器 cookie 卡死**（Keycloak AUTH_SESSION）：短信提交后回弹登录页、execution ID 不变、callback 零到达。换无痕窗口即恢复。教训：怀疑平台故障前，先用无痕/清 cookie 隔离浏览器状态；期间用 `client_credentials`+`scope=openid` 从命令行兜底验证真实端点。
4. **copilot 的 DCR 是死路**（匿名/服务器 IP 均 403 Trusted Hosts），这是放弃平台 IdP、自建 IdP 的决策点。教训：平台能力边界早探测，别在设计依赖它之后才发现。

## 二、MCP 协议与规范落地

5. **FastMCP 的 DNS-rebinding 保护**（默认 allowed_hosts=loopback）让域名直连全部 421。解法不是关保护，而是 Caddy 统一 `header_up Host` 改写——零代码改动且保护仍在。教训：安全默认值先理解再绕行。
6. **MCP 2025 客户端授权请求必带 `resource`（RFC 8707）**，IdP 不启用 resourceIndicators 就报 `invalid_target`；而**带 audience 的 token 会被 userinfo 拒绝**——资源服务器必须走 introspection（RFC 7662）。这两条是配套的，缺一不可。
7. **RFC 9728 资源元数据 + 401 挑战头**是 MCP OAuth 客户端自动发现的入口：401 必须带 `WWW-Authenticate: Bearer resource_metadata=...`，且 `/.well-known/*` 要豁免鉴权（匿名 404 而非 401）。

## 三、凭据卫生（本项目踩过的全部坑）

8. 一天之内抓到**四处**真实凭据硬编码：连接器 secret 作代码默认值、`.env.example` 写真值、README curl 示例写真值、introspection secret 作代码默认值（已进 commit，amend+gc 抹除并轮换）。
   教训：① **fail-fast 优于默认值兜底**——没有默认值就没有泄露；② `.env.example` 与文档示例必须按"占位符"评审；③ 提交前 grep 已知 secret 值是最便宜的扫描；④ 本地仓库无 remote 不等于可以入库，历史会跟着仓库走。
9. **凭据轮换可以零出域**：新值在云端 `openssl rand` 生成、只写入云端两个配置文件，全程不经过聊天上下文与传输通道。
10. **静态 token 的观察期方法论有缺陷**：静态放行路径不打日志，"journal 里 static allow=0"不能证明零使用。可靠依据是"持有方枚举（只有云端 unit + 本人）+ 行为证据（连接器实测全部 OAuth）"。教训：设计灰度指标时先确认该路径真的会产生观测数据。

## 四、运维操作

11. **`ss -tn state established` 显示的是连接端点，不是监听绑定**——曾据此误判服务"仅绑 127.0.0.1"，实际 0.0.0.0。验证绑定用 `ss -tlnp`。
12. **`caddy validate` 有副作用**：以 root 身份打开日志文件，导致随后 reload 时 caddy 用户 permission denied。教训：validate 与 reload 之间检查产物属主。
13. **分片传输会丢字符**（云助手通道 2048 字符限制）：gzip 压缩减片数、`echo -n` 逐片、落盘后长度+md5 双校验；坏片拆半重传。
14. **测试会打到旧进程**：`pkill -f` 匹配不到环境变量（env 不在 cmdline），遗留进程占着端口，新进程 bind 失败但日志看着像启动成功。教训：测试前 `lsof -i :PORT` 确认；判启动成功以 uvicorn 的 running 行为为准（我们自己的 "listening" 日志打在 bind 之前，不可作凭据——本条已记入改进清单）。
15. **遗留进程/临时目录是常态垃圾**：每次测试结束顺手清（进程、/tmp venv、日志文件），并体现在 tasks 模板里。

## 五、协作与流程

16. **OpenSpec 双仓联动有效**：提案先行、归档合并 spec、tasks 勾选留证据，使"择期 remove-static-token"这类跨日遗留能无缝接续。
17. **归档 runbook 里的待办项（5.5）要回勾**，否则提案开了、原 change 永远显示"未完"。
18. **破坏性变更的三件套**每次都灵：快照（tar+unit）→ 基线对照（改前静态 200）→ 改后矩阵（旧 token 401 + 新链路全绿）+ 秒级回滚位。

## 后续改进清单（已识别未做）

- [ ] `server.py` 的 "listening" 日志移到 uvicorn bind 成功之后（见教训 14）
- [ ] 静态命中日志缺失问题随静态通道删除自然消解；如未来再加旁路认证，先写日志再上线
- [ ] IdP 内存态（DCR 客户端/会话）持久化评估（重启丢失，目前可接受）
- [ ] JWT 本地验签（JWKS）替代 introspection 出网调用的演进位（spec 已知限制已记录）
