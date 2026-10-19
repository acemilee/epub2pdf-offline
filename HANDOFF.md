# EPUB2PDF 交接文档（HANDOFF）

> 面向无聊天上下文的接手者。**代码是最终事实源**；若本文与代码冲突，以代码为准并立即修正本文（AGENTS §9.2/§9.3）。
> 根因与踩坑细节集中在 [docs/lessons.md](docs/lessons.md)，本文只保留入口与结论。

## 1. 当前状态

| 项 | 值 |
| --- | --- |
| 当前版本 | **v1.0.1**（2026-10-19） |
| 代码基线 | 发布提交 **`6602927`**（tag `v1.0.1`）；上一版 `v1.0` = commit `752cf64` |
| 运行环境 | Windows 10/11 + Microsoft Edge（本机 **155.0.4283.62**） |
| 开发解释器 | `F:\python313\python.exe`（3.13.9，依赖齐全，含 pytest / pymupdf / pyinstaller）；**仓库内无 `.venv`** |
| 当前计划 | [docs/plans/v1.0.1.md](docs/plans/v1.0.1.md)（v0.3，已执行） |

**功能现状（均已在最终 PDF 上实测）**

- GUI 拖拽转换 + CLI 转换（`python -m epub2pdf --cli`、`run.py`）。
- PDF 书签：CDP `Page.printToPDF(generateDocumentOutline=true)` 生成**多级**书签（真实 400 章书 = 708 条 / 5 层，有标题章节 100% 覆盖）；CDP 不可用时自动降级为锚点书签（扁平）。
- 目录页（EPUB 自带 nav/TOC 页）：套打印样式渲染，**链接下划线已消除**（`POST_EPUB_CSS`，v1.0.1 新增；真实书实测该页下划线绘制 = 0）。
- 字体：全书 GID 并集子集化嵌入系统字体；支持 EPUB 内嵌 webfont（`@font-face src:url()` 重写并注册进浏览器）与 PostScript 字体名（`ArialMT`/`TimesNewRomanPSMT`…）。
- 封面：等比缩放 + 白底居中（`object-fit: contain`），不再裁切。
- 健壮性：取消会中断浏览器进程；`--debug` 打印 traceback；转换输出分阶段耗时；`@charset` 内联安全；元数据写入失败仅告警；下载/取消后任务从运行表移除。

**已知限制（发布时保留）**

- 固定版式 EPUB（漫画/杂志）仍按可重排渲染。
- EPUB 自带 nav/TOC 页保留为内容页（不重制带页码的目录页；仅消除下划线）。
- DRM 加密 EPUB 不支持（`EpubEncryptedError`）。
- PDF 书签来自渲染后的 `h1`–`h6`，不与 NCX 树一一映射；**若 CDP 完全不可用，降级书签为扁平**。
- 封面仅支持浏览器可渲染的位图格式；无 Pillow 兜底（SVG/AVIF 封面仍可能丢）。
- 书内 `<a>` 链接在 PDF 中为链接批注，部分查看器会自行加下划线（GUI 的网页预览同理）；"消除下划线"指 PDF 页面绘制层，不属于 PDF 规范强制项。

**待办 / 下一动作**

1. 发布验证已完成项见 §5；若需重新发布：`git tag -f v1.0.1` 前先核对 `dist/EpubToPdf/EpubToPdf.exe` 是新构建（`dist` 被忽略，不入库）。
2. v1.1 候选见 §8，无 P0 阻塞项。

## 2. 入口与常用命令

```powershell
cd E:\pdfconvert
# 依赖（按需）：pip install -r requirements.txt ; pip install -r requirements-dev.txt

# GUI
F:\python313\python.exe run.py

# CLI
$env:PYTHONPATH='src'
F:\python313\python.exe -m epub2pdf --cli "ebook\某书.epub" -o output\某书.pdf [--timeout 900] [--debug] [--keep-temp] [--no-cover]

# 单元测试（含临时目录隔离，无网络/无 Edge）
F:\python313\python.exe -m pytest -q                 # 期望 48 passed
F:\python313\python.exe -m pytest -q -m e2e          # 期望 6 passed（真实 Edge，约 10s）

# 打包（生成 dist\EpubToPdf\EpubToPdf.exe）
F:\python313\python.exe -m PyInstaller --noconfirm --clean EpubToPdf.spec
```

## 3. 架构与数据流

| 层 | 文件 | 职责 |
| --- | --- | --- |
| L1 解析 | `src/epub2pdf/core/parser.py` | EbookLib 读 EPUB → `EpubBook`（章节/图片/字体/CSS/封面/TOC）；标题取文档顺序首个 `h1`–`h6`（v1.0.1 修） |
| L2 规范化 | `src/epub2pdf/core/normalizer.py` | 写 `assets/`、`fonts/`，重写资源路径与 `@font-face url()`，注入锚点 span（**标题后的兄弟节点**）、合成标题、内联 CSS、输出单文件 `index.html` |
| L3 渲染 | `src/epub2pdf/core/renderer.py` | **CDP 主路径**（`--remote-debugging-pipe` + `Page.printToPDF` + `generateDocumentOutline`，等字体/图片就绪，可取消）→ 失败回退 `--print-to-pdf` CLI |
| L4 组装 | `src/epub2pdf/core/assembler.py` | 封面页、书签（复制 Chromium outline，嵌套/偏移）、元数据、完整性校验（锚点 + `EPBPFEND_DOCUMENT`，单遍抽文本） → 调 L5 |
| L5 字体 | `src/epub2pdf/core/font_embed.py` | 两阶段：按字体资源收集全书 GID 并集 → 子集化系统字体 → 写 `/FontFile2` |
| 编排 | `src/epub2pdf/core/orchestrator.py` / `cli.py` | GUI 任务（QThreadPool，串行 1 并发）/ CLI 单次转换；取消、超时、阶段耗时 |

`normalizer.py` 的 `PRINT_CSS`（A4、中文字体栈、`.chapter{page-break-before:always}`）与 `POST_EPUB_CSS`（TOC 下划线抑制等）是版式核心；锚点常量 `EPBPFANCHOR_`…`_EPBPFANCHOR_END` 与文档尾标记 `EPBPFEND_DOCUMENT` 是 L4 定位依据。

## 4. 本轮（v1.0.1）变更清单

- **D0 下划线**：`POST_EPUB_CSS` 增加 `.chapter a[href]{text-decoration:none}` 等规则（`normalizer.py:119-122`），单测 + 真实书实测。
- **D1 书签**：renderer CDP 主线（`_cdp_print_to_pdf(generate_outline=True)`、就绪等待、取消）；normalizer 锚点移到标题外（避免污染 outline 标题）；assembler `_copy_outline` 递归复制嵌套 outline 并按封面页偏移页码、`_dedupe_title` 折叠 Chromium 因强制分页产生的重复标题；parser 标题支持 `h3`–`h6`。
- **D2 字体**：`font_embed` 两阶段 GID 并集（同字体多页不再只嵌首页）、`_collect_gids_by_font_from_content` 按 `Tf` 资源归属、PS 名别名表；`normalizer` 重写 `@font-face` `url()` 使 EPUB 内嵌字体真正生效。
- **D3 耗时**：`_page_texts` 单遍抽取；真实书 296s → 约 65s。
- **D5 封面**：`object-fit: contain`。
- **健壮性**：`RendererCancelled`、CLI `Popen` 可中断、CDP 中断检查、`--debug`、`EXIT_CANCELLED=130`、分阶段耗时、`@charset` 剔除、元数据告警、orchestrator `pop` 清理。
- **测试基建**：`pymupdf` dev 依赖、`e2e` marker、`tests/fixtures/{basic,cjk,fontsplit}.epub`（`make_fixtures.py` 可重建）、`tests/e2e/*` 断言（书签层级/页码/无污染/图片/下划线=0/字体嵌入/兜底）、`tests/conftest.py` 自动 `tmp_path` 隔离（不再产生 `tests_tmp/`）。
- **发布**：版本号 1.0.1（`__init__.py`、`pyproject.toml`、assembler Producer）、`RELEASE_NOTES.md`、README 更新。

## 5. 验证证据（2026-10-19，本机实测）

| 验证 | 命令/对象 | 结果 |
| --- | --- | --- |
| 单元测试 | `pytest -q` | **48 passed**（约 2s） |
| E2E | `pytest -q -m e2e` | **6 passed**（smoke/bookmarks/fonts，真实 Edge） |
| fixture 断言 | basic/cjk/fontsplit | 书签层级≥3、页码命中、无 `EPBPFANCHOR` 污染、TOC 下划线=0、图片 XObject≥1、Type0 全部有 FontFile、CDP 失败自动降级 |
| 真实中文大书 | `ebook/毛泽东选集…epub` | 1368 页 / 12.7MB / **66.9s**（stages：parse 0.62 / normalize 0.41 / render 9.9 / assemble 55.94；v1.0 为 1358 页 / 296s）；outline 708 条 5 层；30/30 抽查页码命中；目录页下划线绘制 0；链接批注 5719 |
| 真实英文书 | Claude Code 指南 | 212 页 / 3.4MB / 7s；outline 508 条 3 层；无 U+FFFD |
| 真实英文书 | Swing Trading | 76 页 / 4.9MB / 6.3s；outline 3 条（该书仅 4 个 spine 文档，标题来自图片/首章） |
| 打包 | PyInstaller onedir | 构建成功（73.8s）；`dist\EpubToPdf\EpubToPdf.exe --cli` 对 basic.epub 通过 smoke 断言（v1.0.1 起打包入口支持 `--cli` 透传）；GUI 启动写入 `%LOCALAPPDATA%\EpubToPdf\startup.log`，`shown winId=… visible=True` 无 traceback |

## 6. 环境与遗留物

- 根目录仅保留工程文件：`src/ tests/ docs/ ebook/ output/ dist/` + `run.py / EpubToPdf.spec / pyproject.toml / requirements*.txt / README.md / RELEASE_NOTES.md / LICENSE / CONTRIBUTING.md / THIRD_PARTY_NOTICES.md / pixelapple.ico / .gitignore / AGENTS.md / HANDOFF.md`。
- 归档时已删除约 8.3GB 过程产物（`.release/`、`ebook_work/`、`debug/`、`tests_tmp/`、`.venv`、旧 zip）；`ebook/` 为样书、`output/` 为验证 PDF，均被 `.gitignore` 忽略。
- 本机临时调试脚本位于 `%TEMP%\`（如 `analyze_realbook2.py`），不属于仓库。

## 7. 下一任务及动作

- 无 P0/P1 阻塞。建议下一轮：v1.1 规划（见 §8），先补真实大书的**人工观感验收**（封面、目录页、图片页、跨查看器书签）。
- 发布动作：确认 `dist\EpubToPdf\` 为本次构建 → `git tag v1.0.1` → 打 zip 资产（不含样书/PDF）。

## 8. v1.1 候选（未实现，按价值排序）

1. 重制带页码/dot leader 的目录页（原 nav 页仅保留或跳过，见计划 Q3）。
2. NCX/TocNode → PDF 书签映射（层级/标题与 EPUB 目录一致，不再依赖渲染标题）。
3. 封面格式嗅探（SVG/AVIF）或引入 Pillow（计划 Q4）。
4. GUI 内嵌预览去掉 `<a>` 下划线（仅预览层，不影响 PDF）。
5. 大书内存/流式优化（目前 400 章约 13MB PDF 一次性 pypdf 写回）。
6. **GUI「打开输出目录」按钮**（2026-10-19 用户提出，P2 快速项）：顶栏「更改输出目录」旁新增按钮，一键用资源管理器打开当前输出目录，避免用户手动查找。
   - 实现要点：`QDesktopServices.openUrl(QUrl.fromLocalFile(输出目录))`（PySide6 已依赖，无需新库）；目录为空/不存在时按钮置灰并在 tooltip 说明；可选：任务行右键「在文件夹中显示」用 `explorer /select,<pdf>` 定位单个结果。
   - 测试：单测 monkeypatch `QDesktopServices.openUrl` 断言传入路径；不依赖 Edge。
   - 预估 0.2 人日，风险低。

## 9. 变更记录（只留一行摘要，细节见 docs/lessons.md）

- **2026-10-19 v1.1 候选增补**：按用户要求把「GUI 打开输出目录按钮」纳入候选（§8 第 6 项），未开工。
- **2026-10-19 v1.0.1**（commit `6602927`，tag `v1.0.1`）：修复目录页下划线；书签改为 Chromium 多级大纲（CDP 主线 + 锚点兜底）；字体全书并集 + webfont + PS 名；封面 contain；取消/@charset/调试/阶段耗时；补单元+E2E 测试基建；真实书 296s→66.9s。
- **2026-10-19 v1.0.0 基线**（commit `752cf64`，tag `v1.0`）：GUI+CLI+Edge 渲染+封面+锚点书签+字体补写初版。
