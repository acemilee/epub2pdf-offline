# EPUB2PDF 交接文档（HANDOFF）

> 面向无聊天上下文的接手者。**代码是最终事实源**；若本文与代码冲突，以代码为准并立即修正本文（AGENTS §9.2/§9.3）。
> 根因与踩坑细节集中在 [docs/lessons.md](docs/lessons.md)，本文只保留入口与结论。

## 1. 当前状态

| 项 | 值 |
| --- | --- |
| 当前版本 | **v1.1.3**（2026-10-20，bugfix：目录页引导线不再压字；功能基线 v1.1.2 = auto 开本 + 排版度量缩放 + GUI 手动开始 + 容错读 EPUB） |
| 代码基线 | 发布提交 **tag `v1.1.3`**（hash 见 §9）；上一版 `v1.1.2` = `8d86e0d`，`v1.1.1` = `512806f`，`v1.1.0` = `0b04e48` |
| 运行环境 | Windows 10/11 + Microsoft Edge（本机 **155.0.4283.62**） |
| 开发解释器 | `F:\python313\python.exe`（3.13.9，依赖齐全）；**仓库内没有可用的 `.venv`** |
| 当前计划 | [docs/plans/v1.1.2.md](docs/plans/v1.1.2.md)（v0.2，**已执行完成**）；上一版 [docs/plans/v1.1.1.md](docs/plans/v1.1.1.md)（v0.2，已完成） |

**功能现状（均已在最终 PDF 上实测）**

- GUI：拖入文件只**入队**（显示「等待开始」），点工具栏 **开始转换** 才按当前「页面尺寸 / 字号」下拉提交；运行中选项与开始按钮禁用；取消对 pending 行是移除、对运行行是中断浏览器进程。工具栏另有「打开输出目录」。
- CLI：`python -m epub2pdf --cli`、`run.py`；新增 `--page-size {auto,A4,Letter,B5,6x9,7x10}`、`--page-height-pt`、`--font-scale {auto,compact,normal,loose}`。
- **默认 auto 开本**：页面比例取封面图比例（误差实测 ≤ 0.09%），页高默认 9.25in（666pt），正文字号 = clamp(正文宽/40, 9, 13)pt，行距中文 1.55 / 西文 1.40，页边距按页宽比例（左右 11.5%、上 8%、下 9%）；封面满版 `object-fit:cover`。比例超出 0.58–0.86 或无封面 → A4 + WARNING。
- `--page-size A4` 保持 v1.1.1 几何（595.28×841.89pt、18/16/20/16mm、11pt、1.5 行距、封面 contain），供对照回归。
- **生成目录页**：封面后插入带点线和最终页码的目录页，每行可点击；行高/字号/缩进/边距随开本缩放。**v1.1.3 起点线只出现在标题文字与页码之间**（flex 布局），不再从列首贯穿、压住标题。
- **PDF 书签**：默认 CDP `generateDocumentOutline` 多级书签；`--outline-source ncx` 为备选（层级较浅）。
- 字体：全书 GID 并集子集化嵌入系统字体；支持 EPUB 内嵌 webfont 与 PostScript 字体名。
- 封面：magic 嗅探 PNG/JPEG/GIF/WebP/BMP/SVG/AVIF/ICO；auto 满版，A4 等比 contain；TIFF 跳过并告警。
- **页边距由本项目决定**：EPUB 自带 `@page`（含 `margin:0`、纸张尺寸、margin box）被清洗，避免正文贴边。
- **容错读 EPUB**（v1.1.2）：OPF 引用的文件在包内缺失（如 `.xhtml` vs `.html`）时，在**临时副本**上修复后重读；真损坏仍报 `EpubParseError`。TOC 解析对扩展名不敏感。
- 健壮性：取消中断 Edge；`--debug`；阶段耗时；`@charset` 安全；元数据失败仅告警。

**已知限制（发布时保留）**

- 固定版式 EPUB（漫画/杂志，pre-paginated + viewport）仍按可重排渲染；DRM 加密 EPUB 不支持。
- **书签依赖渲染标题**：Chromium outline 只能从实际 `h1`–`h6` 生成。用 `<p class="PartStart">` 等段落模拟标题的书（如 *Advances in Financial Machine Learning*）只有 2 条书签；NCX 备选同样依赖导航标题。
- **正文字号仍受 EPUB 自身 CSS 影响**：auto 只控制根字号与度量；EPUB class CSS 的 em 级联会让部分书正文只有 ~8pt（Systematic 8.0pt、Advances 6.0pt 行内字体）。字号归一化是非目标，列入 §8。
- **EPUB 绝对 px 布局会留大边距**：auto 页面变窄后，若书内用固定 `width:500px` 容器，内容不铺满（Advances 右边距实测约 220pt）。属源文件绝对布局残留。
- 生成目录页条目来自 EPUB 导航中能解析到渲染章节的条目；只列卷名的书只有卷名条目；原 nav 页保留为内容页（链接下划线绘制层已抑制）。
- 若 CDP 完全不可用，书签降级为扁平锚点书签。
- 组装阶段大书 ~23s（PyMuPDF 快路径）；全流程仍受 CDP 渲染影响。
- 书内 `<a>` 在 PDF 中是链接批注，部分查看器会自行加下划线；"消除下划线"指页面绘制层。

**待办 / 下一动作**

1. **下一动作**：无 P0。v1.2 方向见 §8（首推：正文字号归一化 + EPUB 绝对 px 适配），等用户优先级。
2. 回归入口：`F:\python313\python.exe -m pytest -q`（**110 项**全绿，含 e2e 21 项真实 Edge）；`-m e2e` 仅 e2e。

## 2. 入口与常用命令

```powershell
cd E:\pdfconvert
# 依赖：pip install -r requirements.txt（运行时，含 pymupdf）; pip install -r requirements-dev.txt（测试/打包）

# GUI（拖入后点「开始转换」）
F:\python313\python.exe run.py

# CLI（默认 auto 开本）
$env:PYTHONPATH='src'
F:\python313\python.exe -m epub2pdf --cli "ebook\某书.epub" -o output\某书.pdf [--page-size auto|A4|Letter|B5|6x9|7x10] [--page-height-pt 666] [--font-scale auto|compact|normal|loose] [--timeout 900] [--debug] [--keep-temp] [--no-cover] [--outline-source ncx]

# 测试
F:\python313\python.exe -m pytest -q                 # 全部 110 项（含 e2e）
F:\python313\python.exe -m pytest -q -m e2e          # 仅真实 Edge e2e（21 项）

# 打包（生成 dist\EpubToPdf\EpubToPdf.exe）
F:\python313\python.exe -m PyInstaller --noconfirm --clean EpubToPdf.spec
```

## 3. 架构与数据流

| 层 | 文件 | 职责 |
| --- | --- | --- |
| L0 版式 | `src/epub2pdf/core/layout.py` | `compute_layout`/`layout_for_book`：封面头解析（PNG/JPEG/GIF/WebP/SVG）→ 页面比例、尺寸、边距、字号、行距、TOC 缩放、封面填充方式；A4 保持旧几何 |
| L1 解析 | `src/epub2pdf/core/parser.py` | EbookLib 读取（`_read_epub_tolerant` 容忍缺失文件）→ `EpubBook`；标题取文档顺序首个 `h1`–`h6`；递归解析嵌套导航 tuple |
| L2 规范化 | `src/epub2pdf/core/normalizer.py` | 写 `assets/`、`fonts/`，重写资源路径、`@font-face url()`、清洗 EPUB `@page`；按 `Layout` 生成打印 CSS；注入章节 + TOC 锚点；返回 `NormalizeResult(html_path, toc_anchors, layout)` |
| L3 渲染 | `src/epub2pdf/core/renderer.py` | **CDP 主路径**（`Page.printToPDF` + `generateDocumentOutline`，等字体/图片就绪，可取消）→ 失败回退 CLI `--print-to-pdf` |
| L4 组装 | `src/epub2pdf/core/assembler.py` | 封面页 + 目录页 + 正文页；书签（Chromium outline / NCX）；目录行 `Link` 批注；元数据；完整性校验；封面按 `layout.cover_fill` |
| L4.5 目录页 | `src/epub2pdf/core/toc_page.py` | 两遍渲染稳定页码；`scale` 缩放行高/字号/缩进/边距；返回行链接坐标与目标页 |
| L5 字体 | `src/epub2pdf/core/font_embed.py` | 两阶段：全书 GID 并集 → 子集化系统字体 → 写 `/FontFile2` |
| 编排 | `src/epub2pdf/core/orchestrator.py` / `cli.py` | GUI 任务池（串行 1 并发，pending 队列由 `main_window` 管理）/ CLI 单次转换；取消、超时、阶段耗时 |

`normalizer.py` 的 `_PRINT_CSS_TEMPLATE` / `_POST_EPUB_CSS_TEMPLATE`（token 替换）是版式核心；锚点 `EPBPFANCHOR_…_EPBPFANCHOR_END`、TOC 锚点 `EPBPFTOC_<n>`、文档尾 `EPBPFEND_DOCUMENT` 是 L4 定位依据。

## 4. 变更清单

### v1.1.2（2026-10-20）

- 新增 `layout.py`（无第三方依赖）：封面比例 → auto 开本；页高/字号/行距/边距按设计公式缩放；A4 显式模式保持 v1.1.1 几何。
- `normalizer.py`：打印 CSS 模板化并接受 `Layout`；`NormalizeResult.layout`；封面 `object-fit:cover`（auto）。
- `assembler.py`/`toc_page.py`：封面填充方式、TOC 页 scale 与边距随开本；目录 mediabox = 正文。
- `cli.py`/`orchestrator.py`：`--page-size/--page-height-pt/--font-scale` 透传并打印 `layout:` 行。
- `parser.py`：`_read_epub_tolerant`/`_repair_missing_archive_entry`（临时副本修复 OPF 缺失文件）。
- `normalizer._resolve_toc_chapter`：TOC href 扩展名不敏感（`.html`↔`.xhtml`）。
- GUI：拖入入队 + 「开始转换」+ 页面尺寸/字号下拉 + 待开始计数；`QSettings` 持久化；`task_row.mark_pending`。
- 测试：`tests/test_layout.py`、`tests/e2e/test_auto_layout_e2e.py`、`tests/test_main_window.py` 重写、`tests/conftest.py` offscreen；v1.1.1 基线 83 → **110 项**（e2e 14 → 21）。
- 版本 `1.1.2`；README、RELEASE_NOTES 更新；计划 v1.1.2 回填 §10。

### v1.1.1（2026-10-20）

- `normalizer.py`：`_strip_at_page_rules`/`_sanitize_epub_css` 清洗 EPUB `@page`（含 margin box），`POST_EPUB_CSS` 末尾兜底 A4 页边距。
- 测试：fixture `zeromargin.epub` + `tests/e2e/test_page_margins_e2e.py` + 单测。
- `EpubToPdf.spec`：`excludes` 增加 torch/tensorflow/cv2/pandas 等，避免构建污染。

### v1.1.0（2026-10-20）

- 新增 `toc_page.py`（生成目录页、可点击行、两遍稳定页码）；`TocAnchor`/`NormalizeResult`；NCX 备选；封面 magic 嗅探；嵌套导航 tuple 递归；GUI 打开输出目录；PyMuPDF 文本抽取快路径；`--outline-source`。

## 5. 验证证据

**v1.1.2（2026-10-20，本机实测）**

- 测试：`pytest -q` → **110 passed**（e2e 21）；相对 v1.1.1 新增 27 项（e2e +7）。
- 真实书 auto 验收（`testbook/epub` 四本 + 原始损坏版 JS）：

| 书名 | 页面 | 自动页数 | A4 页数 | 目录页/链接 | 书签/层 |
| --- | --- | --- | --- | --- | --- |
| Advances in Financial Machine Learning | 442.9×666 | 266 | 234 | 9 页/250 | 2/1（无 h1–h6） |
| Spec-Driven AI Engineering | 499.5×666 | 341 | 303 | 4 页/114 | 626/3 |
| Systematic Trading | 471.3×666 | 277 | 241 | 6 页/192 | 305/4 |
| 测试驱动开发入门、实战与进阶 | 474.1×666 | 283 | 244 | 1 页/29 | 124/3 |
| Learning JavaScript Design Patterns（原始损坏版） | 507.8×666 | 354 | 283 | 10 页/277 | 392/4 |

  页面比例误差 0.01%–0.09%；封面四边白边 0.00pt；左右边距 = 11.5%W、上 53.3pt（8%H）。
- 原始 JS EPUB：v1.1.2 修复前 ebooklib 直接失败，v1.1.2 **转换成功**（354 页，目录 277 行，书签 392 条/4 层）。
- 打包：`dist\EpubToPdf\EpubToPdf.exe` **12,767,225 B**（12:41 构建，onedir）；`--cli` 转 Systematic 默认 auto → 277 页 / 9.9s / 471.3×666pt；转 `basic.epub --page-size A4` → 57,305 B；GUI 启动日志 `shown winId=1 visible=True`。

**v1.1.3（目录引导线修复）**

- 单测 `test_leader_is_a_flexible_gap_starting_after_the_title` + e2e `test_dot_leaders_do_not_run_under_titles`（basic.epub：dot 矩形与任意文字行 bbox 无水平/垂直重叠）；全量 **112 passed**（e2e 22）。
- 真实书复测：测试驱动开发（中文，474×666pt、283 页）与 Systematic Trading（470.9×666pt、277 页）目测点线均从标题后开始。
- 打包：`dist\EpubToPdf\EpubToPdf.exe` **12,767,136 B**（12:57 重建）；exe `--cli` 转中文书 → 283 页 / 25.0s / 点线重叠 0；转 `basic.epub --page-size A4` → 6 页 / 56,854 B / 元数据 `epub2pdf/1.1.3`；GUI 启动日志 `shown winId=1 visible=True`。

**v1.1.1（@page 修复，保留作对照）**

- `Systematic Trading`：修复前 204 页、197 个正文页中 196 页贴边（最小 -0.66/-3.18pt）；修复后 241 页、坏页 0（minL 44.34 / minR 42.58）。
- 《毛泽东选集》：修复前后均 1381 页、708 条/5 层书签、字体重缺 0。
- 打包 exe：`--cli` 转 zeromargin → 5 页、坏页 0；转 Systematic → 241 页、坏页 0。

**v1.1.0（历史）**

- 《毛泽东选集》（416 章）：1381 页 / 13.4 MB、目录 12 页约 410 行、书签 708 条/5 层；目录页码抽查 30/30；Type0 缺字体 0。
- assemble 270s → 23.3s（PyMuPDF 快路径）；78 项测试（e2e 12）。

## 6. 环境与遗留物

- 解释器：`F:\python313\python.exe`；仓库内 `.venv` 为 uv 空壳（只有 pip），不要用它跑测试。
- Edge：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（155.0.4283.62）。
- `dist/`、`output/`、`ebook/`、`testbook/`、`tests_tmp/` 均被 `.gitignore` 排除；AGENTS.md 也不入库。
- 调试/探针脚本只在 `%TEMP%`（`v112_verify.py`、`v112_acceptance.py` 等），仓库内不保留。

## 7. 下一任务及动作

1. 无 P0 阻塞；v1.1.2 已发布（tag `v1.1.2`）。
2. **下一任务**：与用户确认 v1.2 优先级（见 §8）。建议先做「正文字号归一化」（实测部分书正文 6–8pt）与「EPUB 绝对 px 容器适配」（auto 窄页留白）。
3. 回归入口：`F:\python313\python.exe -m pytest -q`（110 项）、`-m e2e`（21 项真实 Edge）。

## 8. v1.2 候选（未承诺）

| 候选 | 说明 | 依据/状态 |
| --- | --- | --- |
| 正文字号归一化 | 对过小 `font-size` 规则做下限重写（如正文类 < 0.85em 提升），保留表格/图注差异 | 实测 Systematic 正文 8.0pt、Advances 行内 6.0pt；v1.1.2 非目标 |
| EPUB 绝对 px 适配 | 对固定 `width:Npx` 容器按页宽缩放或加 max-width，解决窄页右侧大留白 | Advances 右边距 ~220pt |
| 书签回退 | 无 h1–h6 时用导航中段落锚点/首行文本生成书签 | Advances 仅 2 条 |
| 目录页进阶 | 卷/章两级缩进已支持；超长标题省略号、可选"只列章" | 未立项 |
| 固定版式 EPUB | pre-paginated/viewport 按原始页尺寸渲染 | 当前按可重排，需求未确认 |
| 深色/自定义 CSS | 用户自定义主题 | 未立项 |
| 封面 TIFF | 引入 Pillow 转码 | 已决定不引入（AGENTS §7） |

## 9. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-19 | v1.0.1 | 多级书签（CDP outline）、目录页下划线消除、字体并集嵌入、EPUB 内嵌字体、封面 contain、取消/超时/调试、打包与提交 `6602927` |
| 2026-10-20 | v1.1.0 | commit `0b04e48` / tag `v1.1.0`：生成目录页 + 可点击行、NCX 备选书签、封面 magic 嗅探、嵌套导航解析修复、GUI 打开输出目录、PyMuPDF 快路径 |
| 2026-10-20 | v1.1.1 | tag `v1.1.1`（`512806f`）：清洗 EPUB `@page` + 兜底 A4 页边距、spec excludes 清理构建污染 |
| 2026-10-20 | v1.1.2 | auto 开本（封面比例）+ 排版度量缩放 + GUI 手动开始/选项 + 容错读 EPUB + TOC 扩展名兼容；110 项测试（e2e 21）；计划 v1.1.2 回填 §10；发布提交 `8d86e0d` / tag `v1.1.2` |
| 2026-10-20 | v1.1.3 | 目录页引导线改为 flex 间隙（不再压字/像下划线）；新增单测 + e2e 重叠检测；112 项测试（e2e 22）；112 项全绿 |
