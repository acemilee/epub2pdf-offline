# EPUB2PDF 交接文档（HANDOFF）

> 面向无聊天上下文的接手者。**代码是最终事实源**；若本文与代码冲突，以代码为准并立即修正本文（AGENTS §9.2/§9.3）。
> 根因与踩坑细节集中在 [docs/lessons.md](docs/lessons.md)，本文只保留入口与结论。

## 1. 当前状态

| 项 | 值 |
| --- | --- |
| 当前版本 | **v1.1.1**（2026-10-20，bugfix：不再继承 EPUB 的 `@page` 页边距） |
| 代码基线 | 发布提交 **`512806f`**（tag `v1.1.1`）；上一版 `v1.1.0` = `0b04e48`，`v1.0.1` = `6602927` |
| 运行环境 | Windows 10/11 + Microsoft Edge（本机 **155.0.4283.62**） |
| 开发解释器 | `F:\python313\python.exe`（3.13.9，依赖齐全）；**仓库内没有可用的 `.venv`** |
| 当前计划 | [docs/plans/v1.1.1.md](docs/plans/v1.1.1.md)（v0.2，**已执行完成**）；上一版 [docs/plans/v1.1.md](docs/plans/v1.1.md)（v0.3，已执行完成） |

**功能现状（均已在最终 PDF 上实测）**

- GUI 拖拽转换（工具栏新增**「打开输出目录」**按钮）+ CLI 转换（`python -m epub2pdf --cli`、`run.py`）。
- **生成目录页**：封面后自动插入带点线（dotted leader）和最终页码的目录页；每行可点击跳到对应页。真实 7 卷 416 章书 = 12 页目录 / 约 410 行。
- **PDF 书签**：默认由 CDP `Page.printToPDF(generateDocumentOutline=true)` 生成多级书签（真实书 708 条 / 5 层）；`--outline-source ncx` 可用 EPUB 导航文档生成（同书 410 条 / 3 层）。CDP 不可用时降级为锚点扁平书签。
- 字体：全书 GID 并集子集化嵌入系统字体；支持 EPUB 内嵌 webfont 与 PostScript 字体名（`ArialMT`/`TimesNewRomanPSMT`…）。
- 封面：按内容嗅探格式（PNG/JPEG/GIF/WebP/BMP/SVG/AVIF/ICO）；等比缩放居中不裁切；TIFF 跳过并告警。
- **页边距由本项目决定**（v1.1.1）：EPUB 自带的 `@page`（含 `margin:0`、纸张尺寸、margin box）会被清洗，正文统一使用 A4 + 18/16/20/16mm；EPUB 若未声明 `@page` 则输出与旧版一致。
- EPUB 自带 nav/TOC 页保留为内容页，其链接下划线已被打印样式抑制（不重制原 nav 页）。
- 健壮性：取消会中断浏览器进程；`--debug` 打印 traceback；分阶段耗时；`@charset` 内联安全；元数据失败仅告警。

**已知限制（发布时保留）**

- 固定版式 EPUB（漫画/杂志）仍按可重排渲染；DRM 加密 EPUB 不支持。
- 生成目录页的条目来自 EPUB 导航中能解析到渲染章节的条目；只列卷名的书只有卷名条目。
- NCX 书签比 Chromium 书签层级浅（本书 3 层 vs 5 层）。
- 若 CDP 完全不可用，书签降级为扁平锚点书签。
- 书内 `<a>` 链接在 PDF 中为链接批注，部分查看器会自行加下划线；"消除下划线"指 PDF 页面绘制层。
- 组装阶段的大书耗时已从 ~270 s 降到 ~23 s（PyMuPDF 文本抽取）；全流程仍受渲染影响。
- v1.1 新增目录页后的峰值内存未单独重测（v1.0.1 基线 280.2 MB）。
- **版式行为（不是缺陷）**：EPUB 自带的 `@page` 纸张/页边距/页眉页脚声明一律被忽略（v1.1.1 起）；依赖自定义纸张的 EPUB 会统一排成 A4。
- **已知问题（未修，待决策）**：正文字号主要由 EPUB 自身 class CSS 的 em 值决定（根字号仅 `html{font-size:11pt}`），部分 EPUB 正文只有 ~8pt；调研与四种可选修法见 [docs/plans/v1.1.1.md](docs/plans/v1.1.1.md) §8，是否修需用户拍板。

**待办 / 下一动作**

1. **下一动作**：无 P0；v1.2 候选与字号策略见 §8，等用户优先级。
2. 回归入口：`F:\python313\python.exe -m pytest -q`（83 项全绿）、`-m e2e`（14 项真实 Edge）；真实书命令见 §2。

## 2. 入口与常用命令

```powershell
cd E:\pdfconvert
# 依赖：pip install -r requirements.txt（运行时，含 pymupdf）; pip install -r requirements-dev.txt（测试/打包）

# GUI
F:\python313\python.exe run.py

# CLI
$env:PYTHONPATH='src'
F:\python313\python.exe -m epub2pdf --cli "ebook\某书.epub" -o output\某书.pdf [--timeout 900] [--debug] [--keep-temp] [--no-cover] [--outline-source ncx]

# 测试
F:\python313\python.exe -m pytest -q                 # 全部（含 e2e）
F:\python313\python.exe -m pytest -q -m e2e          # 仅真实 Edge e2e

# 打包（生成 dist\EpubToPdf\EpubToPdf.exe）
F:\python313\python.exe -m PyInstaller --noconfirm --clean EpubToPdf.spec
```

## 3. 架构与数据流

| 层 | 文件 | 职责 |
| --- | --- | --- |
| L1 解析 | `src/epub2pdf/core/parser.py` | EbookLib 读 EPUB → `EpubBook`；标题取文档顺序首个 `h1`–`h6`；**递归解析嵌套导航 tuple**（v1.1 修） |
| L2 规范化 | `src/epub2pdf/core/normalizer.py` | 写 `assets/`、`fonts/`，重写资源路径与 `@font-face url()`，注入章节锚点 + TOC 锚点（标题后兄弟节点），内联 CSS；返回 `NormalizeResult(html_path, toc_anchors)` |
| L3 渲染 | `src/epub2pdf/core/renderer.py` | **CDP 主路径**（`Page.printToPDF` + `generateDocumentOutline`，等字体/图片就绪，可取消）→ 失败回退 `--print-to-pdf` CLI |
| L4 组装 | `src/epub2pdf/core/assembler.py` | 封面页 + 目录页 + 正文页；书签（复制 Chromium outline / NCX 映射）；目录行 `Link` 批注；元数据；完整性校验 |
| L4.5 目录页 | `src/epub2pdf/core/toc_page.py` | 两遍渲染稳定页码；`build_toc_html`（绝对定位行、点线、页码）；返回行链接坐标与目标页 |
| L5 字体 | `src/epub2pdf/core/font_embed.py` | 两阶段：按字体资源收集全书 GID 并集 → 子集化系统字体 → 写 `/FontFile2` |
| 编排 | `src/epub2pdf/core/orchestrator.py` / `cli.py` | GUI 任务（QThreadPool，串行 1 并发）/ CLI 单次转换；取消、超时、阶段耗时 |

`normalizer.py` 的 `PRINT_CSS` / `POST_EPUB_CSS` 是版式核心；锚点 `EPBPFANCHOR_…_EPBPFANCHOR_END`、TOC 锚点 `EPBPFTOC_<n>`、文档尾 `EPBPFEND_DOCUMENT` 是 L4 定位依据。

## 4. 变更清单（v1.1.1 / v1.1.0）

### v1.1.1（2026-10-20）

- `normalizer.py`：新增 `_strip_at_page_rules`（括号配平删除 `@page` 及其嵌套 margin box）与 `_sanitize_epub_css`；`_concat_css` 与内联 `<style>` 都走清洗；`POST_EPUB_CSS` 末尾重新声明 `@page { size: A4; margin: 18mm 16mm 20mm 16mm; }` 作为最后一道兜底。
- 测试：fixture `zeromargin.epub` + `tests/e2e/test_page_margins_e2e.py`（CDP 与 CLI 两条路径、内联 `<style>` 变体）+ `tests/test_normalizer.py` 新增清洗单测。
- `EpubToPdf.spec`：`Analysis.excludes` 增加 torch/tensorflow/cv2/pandas 等无关重型库，避免 PyInstaller 在构建机上误分析（缩小产物体积、缩短构建时间）。
- 版本 `1.1.1`（`src/epub2pdf/__init__.py`、`pyproject.toml`）；`RELEASE_NOTES.md`、`README.md` 同步；计划 [docs/plans/v1.1.1.md](docs/plans/v1.1.1.md) 升 v0.2 并补执行记录。

### v1.1.0（2026-10-20）

- 新增 `src/epub2pdf/core/toc_page.py`：生成式目录页（12 页/410 行，页码与书签一致，可点击）。
- `normalizer.py`：`TocAnchor`/`NormalizeResult`、章级 + fragment 锚点、锚点作为标题后兄弟节点。
- `assembler.py`：`_build_page_index` 单遍索引、目录页插入与 `Link` 批注（`/Dest` 用页对象引用）、NCX 大纲构建、封面 magic 嗅探、TIFF 跳过、PyMuPDF 文本抽取快路径。
- `parser.py`：嵌套导航 tuple 递归（修复目录只列卷名）。
- `renderer.py`：CDP 就绪表达式等 `document.fonts.ready` + 图片 complete；取消支持。
- `ui/shell.py` + `main_window.py`：打开输出目录按钮。
- CLI：`--outline-source {chromium,ncx}`。
- 依赖：`pymupdf` 从 dev 依赖转运行时依赖（性能）。
- 测试：`tests/test_toc_page.py`、`tests/e2e/test_toc_pages_e2e.py`、`tests/e2e/test_toc_fragments_e2e.py`、`tests/e2e/test_cover_formats_e2e.py`、`tests/e2e/test_ncx_outline_e2e.py`、`tests/test_ui_shell.py` 等。
- 文档：`docs/plans/v1.1.md`（v0.3 + 执行记录）、`docs/plans/v1.1-m3-compare.md`（Chromium vs NCX 实验报告）。

## 5. 验证证据（2026-10-20，本机实测）

**v1.1.1（@page 修复）**

- `Systematic Trading`：修复前（v1.1.0 代码基线）204 页，197 个正文页中 **196 页** 左/右边距 < 40pt（最小 -0.66 / -3.18pt）；修复后 **241 页，坏页 0**（最小左 44.34pt / 右 42.58pt）。页数增加是边距生效后的预期重排。
- 《毛泽东选集》：修复前后均 **1381 页**、书签 708 条/5 层、Type0 缺嵌入 0，逐页边距一致；9 个右边界 39.71pt 页为基线已有，非本修复引入。
- `Spec-Driven AI Engineering`：同代码基线（v1.1.0 `0b04e48`）与 v1.1.1 均 **303 页**、左边距 45.34pt；用户旧产物 299 页来自更早版本/不同机器，不能作基线（计划 §10 差异 1）。
- 测试：`pytest -q` **83 项全绿**（e2e 14 项真实 Edge）；`pytest -q -m e2e` 14 passed。
- 打包：`dist\EpubToPdf\EpubToPdf.exe` 重新构建（12,750,156 B，01:53；onedir，需与 `_internal/` 同目录）；`--cli` 转 `zeromargin.epub` → 5 页 / 2.2 s / 边距坏页 0；转 `Systematic Trading` → 241 页 / 11.1 s / 边距坏页 0（minL 44.34 / minR 42.58）；GUI 启动日志 `shown winId=… visible=True`。

**v1.1.0**

- 真实书 `ebook/毛泽东选集 一至七卷…epub`（416 章）：最终 PDF **1381 页 / 13.4 MB**；目录页 12 页 / 约 410 行；书签 708 条 / 5 层（1:8 / 2:16 / 3:387 / 4:253 / 5:44）。
- 目录页码：399 条精确命中；9 条为带脚注号标题（如 `关于辽沈战役〔1〕的作战方针*`）的检查脚本误报，人工核对正确。
- 字体：Type0 字体缺 `FontFile*` 0 处；目录页每页 34 条链接可跳转；目录页无 EPBPFANCHOR 污染。
- 性能：assemble 270 s → **23.3 s**（PyMuPDF 快路径，同 raw.pdf）；整书转换约 45 s（render ~20 s + assemble ~23 s）。
- 测试：`pytest -q` 全绿（**78 项**，含 **12 项 e2e** 真实 Edge）；`-m e2e` 全绿。
- 打包：PyInstaller onedir 构建通过（`dist\EpubToPdf\EpubToPdf.exe`，01:07:32 构建）；实测 `--cli` 转 `tests/fixtures/basic.epub` → 6 页 / 2.1 s，生成目录页 4 行、页码 3–6 正确、4 条可点击链接、书签 5 条；GUI 启动日志 `shown winId=… visible=True`。
- 打包 spec 排除多余 Qt 绑定（`excludes=["PyQt6","PyQt5","PySide2","PySide","tkinter"]`），否则 PyInstaller 报 "multiple Qt bindings packages"（PyMuPDF 依赖扫描会引入 PyQt6 hook）。

## 6. 环境与遗留物

- 解释器：`F:\python313\python.exe`；仓库内 `.venv` 为 uv 空壳（只有 pip），不要用它跑测试。
- Edge：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（155.0.4283.62）。
- `dist/`、`output/`、`ebook/`、`tests_tmp/` 均被 `.gitignore` 排除；AGENTS.md 也不入库。
- 调试脚本已清理；临时探针只在 `%TEMP%`。

## 7. 下一任务及动作

1. 无 P0 阻塞；v1.1.1 已发布（tag `v1.1.1`）。
2. 若要继续演进：先就 §8 的“字号策略”做一次决策（改根字号 / 下限重写 / 仅表格图注 / 不改），再立项；其余候选按用户优先级排期。
3. 回归入口：`F:\python313\python.exe -m pytest -q`（83 项）、`-m e2e`（14 项真实 Edge）。

## 8. v1.2 候选（未承诺）

| 候选 | 说明 | 依据/状态 |
| --- | --- | --- |
| 字号策略 | ①根字号 12pt；②对 `font-size < 0.85em` 规则做下限重写；③仅表格/图注最小 9pt；④不改只写文档 | 调研见计划 §8；需用户选定后立项 |
| 目录页进阶 | 卷/章两级缩进、超长标题省略号、可选"只列章"开关 | 当前已支持 level 缩进；两行换行已限制 |
| 深色/打印版式 | 用户自定义 CSS、纸张大小（Letter/B5） | 未实现，需求未确认 |
| 性能 | 组装阶段已优化；剩余瓶颈在 CDP 渲染大书 | 大书 render ~20 s，可接受 |
| 封面 TIFF | 引入 Pillow 转码 | 已决定不引入（AGENTS §7 最简实现） |
| GUI 预览 | 转换前网页预览 | 无代码基础，已明确非目标 |

## 9. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-19 | v1.0.1 | 多级书签（CDP outline）、目录页下划线消除、字体并集嵌入、EPUB 内嵌字体、封面 contain、取消/超时/调试、打包与提交 `6602927` |
| 2026-10-20 | v1.1.0 | commit `0b04e48` / tag `v1.1.0`： 生成目录页 + 可点击行、NCX 备选书签、封面 magic 嗅探、嵌套导航解析修复、GUI 打开输出目录、PyMuPDF 快路径；计划 v0.3 与对比报告 |
| 2026-10-20 | v1.1.1 | tag `v1.1.1`：清洗 EPUB `@page` + 兜底 A4 页边距（正文贴边修复）、spec excludes 清理构建污染；计划 v0.2 执行记录、lessons 增 @page 条目 |


