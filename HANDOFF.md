# EPUB2PDF 交接文档（HANDOFF）

> 面向无聊天上下文的接手者。**代码是最终事实源**；若本文与代码冲突，以代码为准并立即修正本文（AGENTS §9.2/§9.3）。
> 根因与踩坑细节集中在 [docs/lessons.md](docs/lessons.md)，本文只保留入口与结论。

## 1. 当前状态

| 项 | 值 |
| --- | --- |
| 当前版本 | **v1.1.6**（2026-10-20，原生阅读感：页眉 running head；基线 v1.1.5 = 页脚页码 + 稀疏书签补全 + PDF 语言元数据；v1.1.4 = 目录无横线 + 字号 9pt 下限 + 绝对 px 适配；v1.1.2 = auto 开本 + GUI 手动开始 + 容错读 EPUB） |
| 代码基线 | 发布提交见 §9（tag `v1.1.6`）；上一版 `v1.1.5` = `5a85bd3`，`v1.1.4` = `13eca87`，`v1.1.3` = `7302e24`，`v1.1.2` = `8d86e0d`，`v1.1.1` = `512806f`，`v1.1.0` = `0b04e48` |
| 运行环境 | Windows 10/11 + Microsoft Edge（本机 **155.0.4283.62**） |
| 开发解释器 | `F:\python313\python.exe`（3.13.9，依赖齐全）；**仓库内没有可用的 `.venv`** |
| 当前计划 | [docs/plans/v1.1.2.md](docs/plans/v1.1.2.md)（v0.2，**已执行完成**）；上一版 [docs/plans/v1.1.1.md](docs/plans/v1.1.1.md)（v0.2，已完成） |

**功能现状（均已在最终 PDF 上实测）**

- GUI：拖入文件只**入队**（显示「等待开始」），点工具栏 **开始转换** 才按当前「页面尺寸 / 字号」下拉提交；运行中选项与开始按钮禁用；取消对 pending 行是移除、对运行行是中断浏览器进程。工具栏另有「打开输出目录」。
- CLI：`python -m epub2pdf --cli`、`run.py`；新增 `--page-size {auto,A4,Letter,B5,6x9,7x10}`、`--page-height-pt`、`--font-scale {auto,compact,normal,loose}`、`--no-page-numbers`、`--no-running-headers`。
- **默认 auto 开本**：页面比例取封面图比例（误差实测 ≤ 0.09%），页高默认 9.25in（666pt），正文字号 = clamp(正文宽/40, 9, 13)pt，行距中文 1.55 / 西文 1.40，页边距按页宽比例（左右 11.5%、上 8%、下 9%）；封面满版 `object-fit:cover`。比例超出 0.58–0.86 或无封面 → A4 + WARNING。
- `--page-size A4` 保持 v1.1.1 几何（595.28×841.89pt、18/16/20/16mm、11pt、1.5 行距、封面 contain），供对照回归。
- **生成目录页**：封面后插入带最终页码的目录页，每行可点击；行高/字号/缩进/边距随开本缩放。**v1.1.4 起目录页不再绘制任何横线/点线**：行为纯 flex（标题单行省略号 + 右对齐页码），用户要求的“原生感”以无装饰线实现。
- **字号归一化（v1.1.4）**：EPUB CSS（外部样式表与内联 `<style>`）中任何解析后小于 **9pt** 的 `font-size` 都改写为绝对 `9pt`，覆盖嵌套 em、`%`、`rem`、`px` 与 InDesign/Word 导出的偏小类；大于等于 9pt 的标题/展示字号保持原比例。
- **绝对 px 适配（v1.1.4）**：`width`/`max-width`/`min-width` 的 px 声明若宽于当前文本列，改写为 `min(Npx, 100%)`（`min-width` 置 0），覆盖样式表与内联 `style="..."`；窄 auto 页不再被 500–600px 固定容器撑破。
- **PDF 书签**：默认 CDP `generateDocumentOutline` 多级书签；`--outline-source ncx` 为备选（层级较浅）。**v1.1.5 起**：若 Chromium outline 稀疏（< max(3, 非封面章数×35%)），用章节锚点为缺失章节补扁平书签。
- **页脚页码（v1.1.5）**：组装阶段用 PyMuPDF 在每页底部居中写入物理页码（封面不编号；灰色 0.35、字号 = clamp(0.82×正文字号,7,9)pt），与目录页页码、书签目标一致；`--no-page-numbers` 关闭。
- **页眉 running head（v1.1.6）**：继续页在顶部居中写入小号灰字（章标题，缺失时用书名；CJK 用内置中文字体），章首页因已有大标题而不重复、固定版式/扫描页内容触顶时自动跳过；`--no-running-headers` 关闭。
- **PDF 原生元数据（v1.1.5）**：catalog 写入 `/Lang`（取 EPUB `dc:language`）与 `/ViewerPreferences /DisplayDocTitle true`，阅读器窗口标题显示书名；`<html lang>` 同步为书语言。
- 字体：全书 GID 并集子集化嵌入系统字体；支持 EPUB 内嵌 webfont 与 PostScript 字体名。
- 封面：magic 嗅探 PNG/JPEG/GIF/WebP/BMP/SVG/AVIF/ICO；auto 满版，A4 等比 contain；TIFF 跳过并告警。
- **页边距由本项目决定**：EPUB 自带 `@page`（含 `margin:0`、纸张尺寸、margin box）被清洗，避免正文贴边。
- **容错读 EPUB**（v1.1.2）：OPF 引用的文件在包内缺失（如 `.xhtml` vs `.html`）时，在**临时副本**上修复后重读；真损坏仍报 `EpubParseError`。TOC 解析对扩展名不敏感。
- 健壮性：取消中断 Edge；`--debug`；阶段耗时；`@charset` 安全；元数据失败仅告警。

**已知限制（发布时保留）**

- **固定版式/扫描版 EPUB**（漫画、杂志、扫描书）仍按可重排处理；其文本层由 `transform: scale()` 定位，字号归一化不会改变（*Advances in Financial Machine Learning* 的 6pt 文本层属此类，可见内容来自扫描图）。DRM 加密 EPUB 不支持。
- **书签依赖渲染标题**：Chromium outline 只能从实际 `h1`–`h6` 生成。用 `<p class="PartStart">` 等段落模拟标题的书原本只有 1–2 条书签；v1.1.5 会补章节级扁平书签（*Advances in Financial Machine Learning* 由 2 条增至 6 条），但**章内小节仍无书签**（源文件无真实标题元素）。
- **字号下限是 9pt，不是动态适配**：可见正文众数实测 8.9–9.1pt（v1.1.4），仍有 <0.6% 的可见文字略低于 9pt（排版取整/继承），属可接受范围。
- 生成目录页条目来自 EPUB 导航中能解析到渲染章节的条目；只列卷名的书只有卷名条目；原 nav 页保留为内容页。
- 若 CDP 完全不可用，书签降级为扁平锚点书签。
- 组装阶段大书 ~23s（PyMuPDF 快路径）；全流程仍受 CDP 渲染影响。
- 书内 `<a>` 在 PDF 中是链接批注，部分查看器会自行加下划线；"消除下划线"指页面绘制层。

**待办 / 下一动作**

1. **下一动作**：无 P0。继续「原生感」目标（goal round）：候选见 §8。
2. 回归入口：`F:\python313\python.exe -m pytest -q`（**127 项**全绿，含 e2e 27 项真实 Edge）；`-m e2e` 仅 e2e。
3. v1.1.5 发布后待补：打包产物未再跑真实大书（仅 smoke）。

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
F:\python313\python.exe -m pytest -q                 # 全部 127 项（含 e2e）
F:\python313\python.exe -m pytest -q -m e2e          # 仅真实 Edge e2e（27 项）

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
| L4 组装 | `src/epub2pdf/core/assembler.py` | 封面页 + 目录页 + 正文页；书签（Chromium outline / NCX / 稀疏补全）；目录行 `Link` 批注；页脚页码（PyMuPDF）；元数据 + `/Lang` + `DisplayDocTitle`；完整性校验；封面按 `layout.cover_fill` |
| L4.5 目录页 | `src/epub2pdf/core/toc_page.py` | 两遍渲染稳定页码；`scale` 缩放行高/字号/缩进/边距；返回行链接坐标与目标页 |
| L5 字体 | `src/epub2pdf/core/font_embed.py` | 两阶段：全书 GID 并集 → 子集化系统字体 → 写 `/FontFile2` |
| 编排 | `src/epub2pdf/core/orchestrator.py` / `cli.py` | GUI 任务池（串行 1 并发，pending 队列由 `main_window` 管理）/ CLI 单次转换；取消、超时、阶段耗时 |

`normalizer.py` 的 `_PRINT_CSS_TEMPLATE` / `_POST_EPUB_CSS_TEMPLATE`（token 替换）是版式核心；锚点 `EPBPFANCHOR_…_EPBPFANCHOR_END`、TOC 锚点 `EPBPFTOC_<n>`、文档尾 `EPBPFEND_DOCUMENT` 是 L4 定位依据。

## 4. 变更清单

### v1.1.6（2026-10-20）

- `assembler.py`：新增 `_stamp_running_headers`（PyMuPDF `saveIncr`，章标题/书名、CJK 内置字体、章首页与内容触顶页跳过、宽度省略）、`_top_heading`、`_label_matches_heading`、`_fit_running_head`、`_dict_block_text`、`_CJK_RE`；`assemble(..., running_headers=True)`，从章节锚点构建 `{页:章标题}`（`title_is_fallback` 章节不入页眉，回落书名）。
- `cli.py`：`convert(..., running_headers=True)`；argparse `--no-running-headers`。
- 测试：新 fixture `longchapter.epub`（单章 45 段跨多页）；`tests/test_assembler.py` +2（书名回退/逐页章名、CJK 标题）；`tests/e2e/test_native_reading_e2e.py` +2（续页有页眉、关闭后无页眉）；全量 **131 项**（e2e 29）。
- 版本 `1.1.6`；README/RELEASE_NOTES/HANDOFF/lessons 更新。

### v1.1.5（2026-10-20）

- `assembler.py`：新增 `_stamp_page_numbers`（PyMuPDF `insert_text` + `saveIncr`，封面跳过、居中物理页码、deadline 检查）、`_supplement_outline`/`_flatten_outline_titles`（稀疏 outline 用章节锚点补全，阈值 max(3, 章数×35%)）；`assemble(..., page_numbers=True)`；catalog 写 `/Lang` 与 `/ViewerPreferences /DisplayDocTitle`。
- `normalizer.py`：`_html_lang`（清理 dc:language，缺省 `und`）；`_html5_wrap(..., language=...)` 输出 `<html lang>`，`normalize` 传入 `book.language`。
- `cli.py`：`convert(..., page_numbers=True)` 透传；argparse `--no-page-numbers`。
- 测试：fixture `partialheads.epub`（15 章仅 1 个 `<h1>`）；单测 +4（lang、页码、outline 摊平）；`tests/e2e/test_native_reading_e2e.py` +3（页码=物理页序、关闭后无页码、稀疏书签补全）；全量 **127 项**（e2e 27）。
- 版本 `1.1.5`；README/RELEASE_NOTES 更新；HANDOFF 本文件同步。

### v1.1.4（2026-10-20）

- `toc_page.py`：目录行彻底移除 leader（HTML 不再输出 `.leader`，CSS 无任何 `dotted/dashed` 绘制）；标题 `flex:1` + 8pt 间隙 + 页码固定列。
- `normalizer.py`：`MIN_BODY_FONT_PT=9.0`、`_length_to_pt`、`_normalize_font_sizes`——CSS 与内联 `<style>` 中 <9pt 的 `font-size` 改写为绝对 9pt（保留 `!important`，关键词/calc 不动）。
- `normalizer.py`：`_clamp_px_widths`——超出文本列的 `width/max-width/min-width` px 声明改为 `min(Npx, 100%)` / `0`；同时作用于内联 `style="..."`。
- 测试：新增 fixture `tinyfont.epub`、`pxlayout.epub`；`tests/test_normalizer.py` +6 单测；`tests/e2e/test_typography_e2e.py`、`test_pixel_layout_e2e.py`；e2e 目录页改为「无任何细线」断言。全量 **120 项**（e2e 24）。
- 版本 `1.1.4`；README/RELEASE_NOTES 更新；HANDOFF 本文件同步。

### v1.1.3（2026-10-20）

- 目录点线改为 flex 间隙（不再压字）；追加 e2e 重叠检测；**已被 v1.1.4 的“完全无横线”取代**。

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

**v1.1.6（2026-10-20，本机实测）**

- 测试：`pytest -q` → **131 passed**；新增 `longchapter.epub` e2e 断言续页有页眉、章首页/生成目录页无页眉、`--no-running-headers` 全部关闭；单测覆盖书名回退、逐页章名与 CJK 标题。
- 真实书：`Systematic Trading`（330 页 / 471.3×666pt）297 页带页眉，缺页眉的 33 页均为章首页；页眉为灰色小字，居中于上边距；页脚页码不变（1–330）。
- 固定版式：`Advances in Financial Machine Learning`（266 页，扫描版）内容触顶，全部跳过页眉，不覆盖扫描图。
- 元数据/书签/字体回归不变（Producer `epub2pdf/1.1.6`；405/708 等指标同 v1.1.5）。
- 打包：`dist\EpubToPdf\EpubToPdf.exe` 已重建；`--cli` 转 `longchapter.epub` 输出 6 页、页眉/页码正确；GUI 启动 `visible=True`。

**v1.1.5（2026-10-20，本机实测）**

- 测试：`pytest -q` → **127 passed**（e2e 27）；新增用例覆盖页码、`--no-page-numbers`、稀疏书签、`/Lang` 与 `<html lang>`、`_stamp_page_numbers` 单元。
- 页码：`basic.epub` 6 页，页脚数字依次 1–6；`Systematic Trading`（330 页 / 471.3×666pt）页脚 1–330、封面无数字；`--no-page-numbers` 转换后所有页脚为空。
- 稀疏书签：`Advances in Financial Machine Learning`（7 个 spine 章、源文件仅 1 个真实 `h1`）书签由 2 条增至 **6 条**（`About the Author`、`EULA`、`3.5 Learning Side and Size` 等）。
- 元数据：`basic.pdf` catalog `/Lang = en`、`/ViewerPreferences << /DisplayDocTitle true >>`，经字体内嵌后仍存在；Producer `epub2pdf/1.1.5`。
- 回归：与页码无关的指标保持不变（Systematic outline 305/4 层；Advances 266 页；字体缺嵌入 0）。

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

**v1.1.4（2026-10-20，本机实测）**

- 目录页：e2e 断言目录页 `height<=1pt 且 width>=3pt` 的绘制数量为 **0**；中文《测试驱动开发》重转 283 页 / 474×666pt / 细线绘制 **0**；截图 `output/toc_noline_cn.png` 目测无任何横线。
- 字号归一化（auto，可见文字排除 1px 透明锚点后统计）：

| 书 | 可见正文众数 | <9pt 占比 | v1.1.4 前 |
| --- | --- | --- | --- |
| Systematic Trading | **8.9pt** | 0.56% | 8.0pt |
| Spec-Driven AI Engineering | **8.9pt** | 0.43% | 全文 24.2% 落在 7.5–8.5pt |
| 测试驱动开发（中文） | **9.1pt** | 0.00% | 9.1pt（已达标） |

- 绝对 px：Systematic 生成 HTML 中 **15 处**超宽 px 容器被改写为 `min(Npx,100%)`；fixture `pxlayout.epub`（600px 容器 + 300×450 封面、443×666pt 页）正文右边距通过 ≤90%W 断言。Spec 的 px 容器均小于文本列宽（不触发）；Advances 为扫描版无 px 宽度。
- 测试：`pytest -q` → **120 passed**（e2e 24）；全量两次 exit 0。
- 打包：`dist\EpubToPdf\EpubToPdf.exe` **12,769,049 B**（v1.1.4，13:10 构建，onedir）。exe smoke：
  - `--cli basic.epub --page-size A4` → 6 页 / 595×841.9pt / 目录页细线 0 / 书签 5 / 元数据 `epub2pdf/1.1.4`；
  - `--cli 测试驱动开发…epub`（默认 auto）→ **284 页 / 474×666pt / 目录页细线 0 / 书签 124 / 可见正文众数 9.1pt**；
  - GUI 启动日志 `app: shown winId=1 visible=True`。

**v1.1.3（目录点线，已被 v1.1.4 取代）**

- 当时用 flex 间隙承载点线并通过“无重叠”e2e；用户仍认为横线破坏原生感，v1.1.4 直接删除绘制。

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

1. 无 P0 阻塞；v1.1.6 已发布（tag `v1.1.6`）。
2. **当前目标（goal）**：继续追求「原生感」、改善阅读观感。已落地页脚页码、页眉 running head、稀疏书签补全、`/Lang` 元数据；下一批候选见 §8（首推：章内小节书签提取、目录页排版微调）。
3. 回归入口：`F:\python313\python.exe -m pytest -q`（131 项）、`-m e2e`（29 项真实 Edge）。

## 8. 后续候选（未承诺）

| 候选 | 说明 | 依据/状态 |
| --- | --- | --- |
| 小节书签提取 | 从 `<p class="PartStart">` 等样式化段落识别标题（按 class/字号/加粗启发式），补章内小节书签 | Advances 章内小节仍无书签 |
| 目录页进阶 | 超长标题两行、可选“只列章”、是否省略导航页条目 | 未立项 |
| 固定版式 EPUB | 识别 pre-paginated/viewport 与扫描版，按原始页尺寸渲染 | 当前按可重排，需求未确认 |
| 深色/自定义 CSS | 用户自定义主题 | 未立项 |
| 封面 TIFF | 引入 Pillow 转码 | 已决定不引入（AGENTS §7） |

> 页眉 running head 已在 v1.1.6 落地；书签回退（章节级）在 v1.1.5；字号归一化与绝对 px 适配在 v1.1.4。扫描版文本层的 6pt 属固定版式问题。

## 9. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-19 | v1.0.1 | 多级书签（CDP outline）、目录页下划线消除、字体并集嵌入、EPUB 内嵌字体、封面 contain、取消/超时/调试、打包与提交 `6602927` |
| 2026-10-20 | v1.1.0 | commit `0b04e48` / tag `v1.1.0`：生成目录页 + 可点击行、NCX 备选书签、封面 magic 嗅探、嵌套导航解析修复、GUI 打开输出目录、PyMuPDF 快路径 |
| 2026-10-20 | v1.1.1 | tag `v1.1.1`（`512806f`）：清洗 EPUB `@page` + 兜底 A4 页边距、spec excludes 清理构建污染 |
| 2026-10-20 | v1.1.2 | auto 开本（封面比例）+ 排版度量缩放 + GUI 手动开始/选项 + 容错读 EPUB + TOC 扩展名兼容；110 项测试（e2e 21）；计划 v1.1.2 回填 §10；发布提交 `8d86e0d` / tag `v1.1.2` |
| 2026-10-20 | v1.1.3 | 目录页引导线改为 flex 间隙（已被 v1.1.4 取代）；112 项测试（e2e 22）；发布提交 `7302e24` / tag `v1.1.3` |
| 2026-10-20 | v1.1.4 | 目录页彻底无横线；字号归一化（9pt 下限）；绝对 px 容器 clamp；120 项测试（e2e 24）；发布提交 `13eca87` / tag `v1.1.4` |
| 2026-10-20 | v1.1.5 | 页脚页码（`--no-page-numbers` 可关）；稀疏书签用章节锚点补全；`/Lang` + `DisplayDocTitle`；`<html lang>` 取书语言；127 项测试（e2e 27）；发布提交 `5a85bd3` / tag `v1.1.5` |
| 2026-10-20 | v1.1.6 | 页眉 running head（章名/书名、CJK、章首页与扫描页跳过，`--no-running-headers` 可关）；131 项测试（e2e 29）；发布提交与 tag 见 `git log`（v1.1.6） |
