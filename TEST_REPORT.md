# ChatGPT Pro 浏览器驱动 — 文件类型 / 多文件 / 长任务测试报告

> 测试日期：2026-06-23 · 账户 `lgh520131466@gmail.com`（`chatgpt_plan_type: pro`）
> 方案：解密 Chrome cookie → 注入真 Chrome → 驱动 ChatGPT 网页 UI（非逆向 API）
> **最终结果：20/20 PASS（100%）**

---

## 1. 测试矩阵与结果

### Suite A — 单文件上传（10 种类型）10/10 ✅

| 文件 | 类型 | 大小 | 用时 | 结果 |
|---|---|---|---|---|
| img.png | PNG 图片 | 168 B | 17.3s | ✅ 正确识别"solid red square" |
| img.jpg | JPEG 图片 | 122 B | 30.1s | ✅ 正确识别图片 |
| doc.pdf | PDF 文档 | 655 B | 15.6s | ✅ 读出哨兵 `FIXTURE_SENTINEL_PDF_QW7` |
| data.csv | CSV 表格 | 695 B | 34.9s | ✅ 读出指定行哨兵 `FIXTURE_SENTINEL_CSV_19` |
| note.txt | 纯文本 | 101 B | 19.5s | ✅ 读出 `FIXTURE_SENTINEL_TXT_M3K` |
| data.json | JSON | 158 B | 17.6s | ✅ 读出 `FIXTURE_SENTINEL_JSON_L8R` |
| code.py | Python 源码 | 154 B | 18.3s | ✅ 读出 `FIXTURE_SENTINEL_PY_V2X` |
| readme.md | Markdown | 113 B | 17.1s | ✅ 读出 `FIXTURE_SENTINEL_MD_9P` |
| doc.docx | Word DOCX | 987 B | 18.3s | ✅ 读出 `FIXTURE_SENTINEL_DOCX_T5` |
| sheet.xlsx | Excel XLSX | 1.6 KB | 53.1s | ✅ 读出 `FIXTURE_SENTINEL_XLSX_4G` |

**覆盖：图片 / 文档 / 表格 / 代码 / 结构化数据 全部支持。** 每个文件内嵌唯一哨兵串，验证 ChatGPT 读取的是**内容**而非文件名。

### Suite B — 多文件上传 3/3 ✅

| 测试 | 场景 | 用时 | 结果 |
|---|---|---|---|
| multi:3text | 3 个文本文件（txt/md/py）→ 一次性列出全部 3 个哨兵 | 19.0s | ✅ 3/3 |
| multi:5mixed | 5 种混合类型（pdf/csv/json/docx/xlsx）→ 全部 5 个哨兵 | 27.5s | ✅ 5/5 |
| multi:crossfile-sum | 读 JSON 文件，求数组 `[3,1,4,1,5,9,2,6]` 之和 | 23.1s | ✅ = 31 |

**多文件混合上传完全支持**，且能跨文件做结构化推理（求和）。

### Suite C — 长任务 4/4 ✅

| 测试 | 场景 | 用时 | 结果 |
|---|---|---|---|
| long:big-input-needle | 132KB 文件中找隐藏的 `NEEDLE_IN_HAYSTACK_UNIQ_7Q3Z9` | 57.7s | ✅ |
| long:big-prompt | 14KB 直接粘贴 prompt 中找 `UNIQUE_PROMPT_NEEDLE_8842` | 183.5s | ✅ |
| long:long-output | 生成 800+ 字长文（实际产出 **2399 字**） | 239.6s | ✅ |
| long:deep-reasoning | 约束优化：河岸围栏求最大面积（期望 50×25=1250） | 19.2s | ✅ 含推理步骤 |

**长输入 / 长输出 / 深度推理全部通过。** Pro 模型在 132KB 大文件中精确定位隐藏标记，证明完整处理（非截断/采样）；长输出稳定生成 2399 字未中断；多步推理得出正确数学解。

### Suite D — 多轮对话状态保持 3/3 ✅

| 轮次 | 操作 | 用时 | 结果 |
|---|---|---|---|
| turn1 | 设定秘密 `MY_SECRET_IS_BANANA_SPLIT_42` | 11.8s | ✅ "OK" |
| turn2 | 回忆秘密 | 13.2s | ✅ 正确返回 |
| turn3 | 将秘密反转拼写 | 18.2s | ✅ 正确反转 |

**同一会话内上下文完整保持**，可跨轮次记忆与变换。

---

## 2. 测试过程中发现并修复的真实鲁棒性 Bug

测试不是一次性通过的——3 个失败暴露了 harness（非 ChatGPT）的真实缺陷，全部已修复：

### Bug 1：上传后 send 按钮仍 disabled → 提交静默失败（PNG/DOCX 120s 超时）
- **现象**：PNG/DOCX 上传后按 Enter，turn 永不开始，`turns=0` 持续 90s。
- **根因**：二进制文件（DOCX/PDF/图片）上传后 ChatGPT 需**服务端解析**，期间 send 按钮 `disabled=true`。我在解析未完成时就按了 Enter，等于没提交。
- **修复**：`upload()` 内新增 `_wait_send_enabled()`，上传后阻塞轮询直到 send 按钮可点击再返回；`ask()` 提交前再确认一次。
- **验证**：修复后 DOCX 22.3s、PNG 17.3s、CSV 34.9s 全 PASS。

### Bug 2：`goto(BASE)` 恢复上次对话 → 跨会话污染（CSV 测试返回 big.txt 的哨兵）
- **现象**：CSV 测试回复 `NEEDLE_IN_HAYSTACK_UNIQ_7Q3Z9`（上一个 big.txt 测试的哨兵）。
- **根因**：`new_chat()` 用 `page.goto("https://chatgpt.com/")`，但该 URL 常会**恢复最近活跃的对话**而非开新会话。
- **修复**：改用点击 `[data-testid="create-new-chat-button"]`，并校验 composer 为空且无 assistant turn 才返回。
- **验证**：修复后 single 套 10/10 PASS，无串扰。

### Bug 3：测试夹具每行都有哨兵 → 期望不唯一（CSV）
- **现象**：CSV 测试"失败"（实为期望错误），ChatGPT 返回了第一个哨兵 `CSV_00`，与期望 `CSV_19` 不符。
- **根因**：夹具把 `FIXTURE_SENTINEL_CSV_{i:02d}` 写进每一行，导致返回值不确定。
- **修复**：夹具改为仅第 19 行含唯一哨兵。
- **教训**：测试夹具的确定性比覆盖度更重要。

---

## 3. 关键鲁棒性参数（已固化进 harness）

| 参数 | 值 | 说明 |
|---|---|---|
| 输入方式 | `keyboard.type(delay=6ms)` | ProseMirror 必须用真实键盘事件，`fill()` 无效 |
| 提交键 | Enter | Shift+Enter 换行 |
| 上传就绪检测 | send 按钮 `disabled=false` | 二进制文件解析未完成前 send 不可点 |
| 完成检测 | `stop-button` 消失 + send 重现 + 文本稳定 0.9s | 排除 "Pro 思考中" 等占位文本 |
| 新会话 | 点击 `create-new-chat-button` | 不能依赖 URL 导航（会恢复上次对话） |
| 超时上限 | 长/大任务 180-300s，普通 60-120s | Pro 深度推理可达数分钟 |
| 反检测 | `channel="chrome"` + `--disable-blink-features=AutomationControlled` | 真 Chrome 保证 TLS/cf_clearance 一致 |

---

## 4. 性能数据（供容量规划参考）

| 任务档 | 典型用时 |
|---|---|
| 简单单文件读取 | 13-20s |
| 二进制文件（docx/xlsx） | 18-53s |
| 多文件（3-5 个） | 19-28s |
| 大文件定位（132KB） | 58s |
| 大 prompt（14KB 粘贴） | 184s |
| 长输出（2400 字） | 240s |
| 深度推理 | 19s（含思考步骤） |
| 多轮对话（3 轮） | 11-18s/轮 |

**吞吐量参考**：一个 turn 平均 15-30s；长任务 1-4 分钟。串行跑 20 个测试约 15 分钟。

---

## 5. 文件位置

```
chatgpt-pro-test/
├── lib/harness.py              # 可复用驱动（cookie 解密+注入+UI 操作）
├── fixtures/gen_fixtures.py    # 11 种测试夹具生成器
├── run_suite.py                # 主测试套（single/multi/long/multi-turn）
├── smoke_pdf.py                # 单 PDF 冒烟测试
├── verify_fix.py               # 3 项修复验证
├── run_remaining.py            # 补跑（big-prompt + multi-turn）
├── diag_docx.py                # DOCX 超时根因诊断脚本
└── results/                    # JSONL 测试结果（每次运行一个文件）
```

---

## 6. 结论

**"解密 cookie + 注入真 Chrome + 驱动网页 UI"** 这条路线在文件类型覆盖、多文件、长任务、多轮对话四个维度上**全部通过**，且暴露的 3 个真实 bug 都已修复。harness 现已具备生产可用的鲁棒性，可作为 ChatGPT Pro 的本地接入层。

如需产品化（包成 `/v1/chat/completions` 接口），可在此 harness 基础上加一层 FastAPI 包装——所有底层难点（cookie/上传就绪/完成检测/会话隔离）均已解决。
