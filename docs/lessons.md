# Lessons（踩坑与根因记录）

> 本文件保存根因、排查方法和踩坑细节；HANDOFF.md 只保留一行指针。
> 按时间倒序，每条注明日期与版本/基线。

## 2026-10-19（第 3 次）· v1.0.1 书签路线 spike（B：CDP generateDocumentOutline）

### 1. Edge 155 支持 CDP 生成 PDF 大纲，CLI 参数不支持

- 本机 Edge `155.0.4283.62`：`Page.printToPDF(generateDocumentOutline=true)` 成功产出带层级的大纲；CLI 的 `--generate-document-outline` **无效果**（outline 为空）。只能通过 CDP 用。
- 真实大书（415 个非封面章节）：708 条 outline / 5 层（8/16/387/253/44）；有标题的 412 章 100% 命中；抽查 30 条页码全对；标题无锚点污染；PDF 1357 页/18.29MB/9.3s；图片 XObject 4 个（与 CLI 一致）。
- `pypdf PdfWriter.append(raw_reader, import_outline=True)` 在已加 1 页封面后仍正确：outline 页码自动 +1，无需手工平移（pypdf 6.13 实测）。
- **教训**：PDF 书签不必自己从文本锚点反推页码；Chromium 已能从 HTML 标题生成层级大纲，成本更低、结果更准。自己维护锚点只应作为 CDP 不可用时的兜底。

### 2. Chromium 开关必须 `--switch=value` 单 token

- 用 Python `subprocess` 传 `["--remote-debugging-port", "9877"]` 时 Edge 直接退出并报 `Multiple targets are not supported in headless mode.`；改成 `--remote-debugging-port=9877` 才正常。
- `renderer._build_cdp_edge_cmd` 现有实现用的是 `=` 单 token，正确；手工写探针时容易踩。

### 3. CDP 打印前必须等字体/图片就绪

- 只等 `document.readyState=="complete"` 不够稳：应再等 `document.fonts.ready` 且 `[...document.images].every(i=>i.complete && i.naturalWidth>0)`，否则可能出现缺图/缺字。
- 实测：加就绪等待后，`basic` 级图片页 image XObject 与 CLI 一致；此前一次不完整探针报告 0 图片，根因是 spike 脚本把清洗后的 HTML 写到 assets 之外，**不是** CDP 缺陷——也提醒：验证丢图要先确认路径，再归因渲染器（AGENTS 11.1）。

### 4. 锚点放在标题内部会污染大纲标题

- 原 `normalizer` 把 1px 透明锚点 span 插进 `h1`/正文首个标题内部；CDP 生成 outline 时标题文本变成 `Chapter 2EPBPFANCHOR_ch2_EPBPFANCHOR_END`。B 路线必须把锚点移到标题元素之后（兄弟节点），A 兜底仍可从前言文本流中找到 marker。
- **教训**：任何"隐藏但参与文本流"的标记都不要插进标题元素，否则会被 PDF 结构（大纲/书签）采集。

### 5. Parser 只认 h1/h2，h3 章节标题退化成文件名

- `parser._extract_title_from_xhtml:148-161` 只遍历 `h1`、`h2`、`title`；《毛泽东选集》章节标题用 `h3`，导致 392/416 章 `title_is_fallback=True`（如 `Section0101.xhtml`）。
- 影响：合成标题、CLI/GUI 日志、A 兜底的章节名质量；不影响 B 的 outline（B 用渲染后的标题）。修法：按文档顺序取第一个 `h1`–`h6`（T2.7）。

## 2026-10-19（第 2 次）· v1.0.0 基线 + TOC 下划线修复 + 归档

### 1. PDF 目录页链接下划线：nav 页被当正文渲染，`<a>` 保留 UA/EPUB 链接样式

- **现象**：用户截图显示转换出的 TOC 页每条链接都带下划线（部分蓝色），PDF 看起来像网页。
- **根因（代码核实）**：`parser` 把 spine 中的 nav/toc.xhtml 当普通章节 → `normalizer.normalize` 包成 `.chapter` 渲染；`<a>` 的 `text-decoration: underline` 来自 UA 默认样式（部分 EPUB CSS 还显式设置 `a{color:#06c;text-decoration:underline}`）。原 `PRINT_CSS`/`POST_EPUB_CSS` 都没有 `a` 规则，所以原样保留。
- **修复**：`normalizer.py:119-122`（`POST_EPUB_CSS` 内）：`a, a:link, a:visited, a:hover, a:active { color: inherit !important; text-decoration: none !important; }`。该块由 `_html5_wrap():379` 排在内联 EPUB CSS **之后**，因此能覆盖 EPUB 样式（`@charset`/内联 `style` 属性的风险见 plan C2）。
- **验证方法（可复用）**：
  1. 单测 `tests/test_normalizer.py::test_normalize_removes_link_underline_and_link_color_from_epub_anchor_styles`：断言规则存在，且位于 EPUB CSS 之后（先红后绿）；
  2. 渲染实测：自建 3 页 fixture EPUB（toc 页链接带 EPUB 下划线+蓝色）→ 转换 → 用 PyMuPDF 统计 TOC 页 `get_drawings()` 中的水平短线/扁矩形数：**修复前 2 / 修复后 0**；目视对比颜色由蓝变黑。
- **教训**：打印外观要在最终 PDF 上用矢量/像素证据验证，不能只看 HTML。“原生 PDF 感”= 去掉交互式网页语义（链接色、下划线）；同时注意 `<a>` 在 PDF 里本就不可点击（normalizer 注释已说明）。

### 2. 工作区归档：删除前逐项 Resolve-Path 校验

- `.release/` 有 41 个历史快照/重复 zip（约 8.0GB），只保留最新且最完整的 `EpubToPdf-v1.0-windows-x64-final-stable-serial-integrity/`，重命名为 `dist/EpubToPdf/`。
- 删除前用 `Resolve-Path` 对每个目标断言 `StartsWith('E:\pdfconvert')`，再 `Remove-Item -Recurse -Force`；删除的目录全在 `.gitignore` 内（非源码）。
- `ebook/`（4 个真实样本）保留；`.claude/`（本地 agent 配置）保留。
- `.venv/` 是 uv 空壳（只装 pip），删除；统一用 `F:\python313\python.exe`。

### 3. 测试会污染工作区（待修，plan T1.4）

- `tests/test_cli.py` 硬编码写入 `tests_tmp/`（跑一次留 531 文件/42MB）；后续应改 `tmp_path`，TDD 落地前先接受该目录会被重建。

## 2026-10-19 · v1.0.0 基线交接（只读核查 + e2e 实测）

### 1. 书签大面积丢失：1px 透明锚点被抽成逐字符带空格的文本

- **结论**：`normalizer` 注入的 `EPBPFANCHOR_<id>_EPBPFANCHOR_END` 是 `font-size:1px; color:transparent` 的 inline span；在部分 EPUB 样式/字体上下文中，Edge 把它们按字符逐个定位绘制，`pypdf` 抽取文本时在字符之间插入空格（raw.pdf 第 2 页实测为 `E P B P F A N C H O R _ …`）。`assembler.ANCHOR_RE` 不允许空白，导致 `_find_anchor_pages` 找不到；最终 outline 只有 4 条，`_add_outline` 因为 `added>0` 也不加 "Contents" 兜底。
- **证实方式（可复现）**：
  1. `--keep-temp` 跑一次转换，保留 `raw.pdf`；
  2. 逐页 `PdfReader.page.extract_text()`，打印前 8 页可见空白化 marker；
  3. 对每页先 `re.sub(r"\s+", "", text)` 再匹配锚点：`415/415` 全部命中（单遍约 105 s）；
  4. 用 1px/11pt/8pt 三个小 HTML 探针做对照：独立场景下 1px 也能干净抽取 → 说明是「继承 CJK 样式 + 1px」的组合触发，而非绝对失效。
- **教训**：不要把「文本能否被 PDF 抽取」当成必然；隐藏文本的抽取结果依赖字体度量和定位方式。验证必须在最终 PDF 上做（AGENTS 11.4），单元测试只校验 HTML 里的 marker 存在（`test_normalizer.py`）不足以覆盖书签功能。

### 2. `.venv` 是 uv 空壳，规定测试命令不可用

- 仓库内 `.venv` 由 uv 创建（`pyvenv.cfg: home=F:\python313`、`include-system-site-packages=false`），只装了 `pip`；`README.md:91-95` 的依赖安装步骤从未在本机执行。
- 因此 `.\.venv\Scripts\python.exe -m pytest -q` 直接 `No module named pytest`（exit 1）。改用系统解释器 `F:\python313\python.exe`（依赖齐全）后 24 passed。
- **教训**：交接时先确认「命令能否在本机跑通」，不要只看 README；解释器路径要写进 HANDOFF。

### 3. 字体嵌入的两个静默缺口

- `find_system_font('ArialMT')`/`'TimesNewRomanPSMT'`/`'CourierNewPSMT'` 返回 `None`，但 `C:\Windows\Fonts\arial.ttf`/`times.ttf`/`cour.ttf` 存在 → 名称映射表缺 Edge 常见 BaseFont 名，最终 PDF 里这些字体不嵌入且只打 WARNING。
- `font_embed._get_subset` 以 family 为 key 缓存「第一次遇到该 family 的那一页」的 GID 子集，后续页面直接命中 `already-embedded` 跳过；同字体后页新增的字符不会进子集 → 缺字风险。正确做法是先收集全书 GID 并集再子集化。
- **教训**：字体处理要按「全书字体→GID 集合」建模，而不是逐页处理；WARNING 级别降级会掩盖问题，验收时应把 `no-system-font` 视为失败。

### 4. 大书耗时与超时语义

- `毛泽东选集`（2.78 MB / 416 章）单次转换 296 s：渲染 17.5 MB raw.pdf，组装阶段又把全书文本抽取 3 遍（`assembler.py:193/195/229`），单遍约 105 s。
- CLI `--timeout` 是**总超时**（`cli.py:64-80`），`--timeout 300` 在这本书上必然失败；GUI 完全不传超时（`main_window.py:164-167`）。
- **教训**：性能验收要用真实大书；超时必须文档化为「总时长」并给大书留足余量。

### 5. 其他

- 发布遗留（`.release/`、`ebook_work/`、`debug/`、`tests_tmp/`）全部被 gitignore，但占用磁盘大；清理前需确认不包含唯一的验证证据。
- 打包产物（06-19）未在本轮重跑，不能假设源码改动会自动进入已有 exe（AGENTS 11.4）。
