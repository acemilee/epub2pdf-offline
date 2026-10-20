# Lessons（踩坑与根因记录）

> 本文件保存根因、排查方法和踩坑细节；HANDOFF.md 只保留指针。
> 按时间倒序，每条注明日期与版本/基线。

## 2026-10-20 · v1.2.0：平面导航靠标题编号恢复层级

- **现象**：InDesign 类 EPUB 的导航文档常是平面列表（*Advances in Financial Machine Learning* 的 244 个条目全部同级）。v1.1.7 改用导航补书签后，条目数量够了，但在 PDF 里 244 条全是顶层，阅读器目录仍然“平铺”。
- **方法**：标题编号本身编码了层级——`1` → 0、`1.1` → 1、`1.1.1` → 2，`Chapter N`/`Appendix X` → 0；`16.A.1` 这类字母段也按段数计层（正则要让字母段参与，否则会被当成顶层）。只对“原始层级只有一层且 ≥60% 标题带编号”的导航生效，已有层级的导航保持原样。
- **防跳级/防误判**：每步最多比上一级深一层（`min(inferred, previous+1)`），避免 `2.3.4` 在缺少父节点时直接变成第三层；数字段限 1–3 位，四位数（年份）不识别。副作用是极端不规范的编号可能被压平一级，但树结构始终合法。
- **验收口径**：书签质量 = 条目数 × 层级。只看条目数会得到“条目齐全但平铺”的假完成；必须同时看深度直方图和父子链（例如 `1.1 Motivation` 的 parent 是否为 `Chapter 1`）。v1.2.0 实测 Advances：244 条、深度 1→2、{98 顶层,146 子项}，而 Chromium 大纲本就丰富的书（Systematic 305/4、中文书 124/3）保持不变。

## 2026-10-20 · v1.1.9：链接要“像书”，就要同时改绘制层与目标层

- **链接文字变蓝的真实来源**：EPUB 里常见 `span.URL { color: blue; text-decoration: underline }` 或 `a { color:#0000ff }`。只覆盖 `a` 不够——InDesign/Word 导出常把颜色放在链接内部的 `<span>` 上，所以打印 CSS 必须同时写 `a, a:visited { ... }` 和 `a * { color: inherit !important; text-decoration: none !important; }`。改完要在最终 PDF 上按 span 颜色统计验证（*Systematic Trading* 蓝色 span 276 → 0）。
- **跨文件 href 会变成 file 链接**：EPUB 正文里 `href="chapter2.xhtml#note"` 在 Chromium 打印后是“打开临时 HTML 文件”的 file 链接（kind 3），在 PDF 阅读器里会弹文件选择器。必须在生成 HTML 前把跨文件 href 归一为 `#fragment`：能解析到目标章时用目标章首锚点（`_chapter_link_map`），否则降级为纯 `#fragment`。保留 `http(s)`/`mailto` 不动。
- **同文件 `#fragment` 的页码不在锚点索引里**：Chromium 把 `<a href="#glossary">` 解析成 catalog `/Dests` 的命名目标（`/D [page /XYZ ...]` 或 `/Page` 字典），名字通常是 `glossary` 而不是 `EPBPFANCHOR_*`。原先只按锚点索引匹配，就会把所有交叉引用当死链删掉。正确做法：先从 raw PDF 的 `/Dests` 建 `{名称: 原始页号}`，最终页 = 原始页 + 封面/目录偏移；pypdf 对这种项可能返回 `Destination` 对象（含 `/D` 数组或 `/Page`），两种形态都要处理。实测 *Systematic Trading*：页内链接 137 → **1071**，file 链接 934 → 0。
- **验证口径**：链接是否“原生”要同时看 ①可见层（文字颜色/下划线）②注释层（kind 4 页内链接 vs kind 3 file 链接 vs kind 2 URI）③目标页码（抽查引用跳转页文本是否包含目标词）。只看注释数量会被“死链被删光”误导。

## 2026-10-20 · v1.1.8：目录页折行要“先量后画”，书签标题要防 Chromium 重复

- **固定行高装不下长标题**：目录页原来每行固定 20pt、`nowrap + ellipsis`，长章名被截成 `…`。正确做法是**量测式布局**：先用字符宽度估算（CJK/全角按 1em，ASCII 按约 0.55em，再留 5% 安全余量）把标题分成 1–2 行，按行数给出该行高度，再绝对定位；CSS 侧用 `-webkit-line-clamp: 2` 作为最终兜底，链接矩形按整行高度画。先量后画保证“行高、行距、页码/链接”三者一致，不会出现文字折行压到下一行的经典事故。
- **Chromium outline 会把折行标题重复一遍**：标题在页面渲染中折成两行时，`generateDocumentOutline` 输出的标题是两行文本直接拼接（可能连空格都没有），例如 `...Does Not` + `...Fit On...` → `...Does Not...Does NotFit On...`。处理方式：在 `_dedupe_title` 里找**最长重复前缀**并折叠，再按拼接边界字符补回空格（两侧都是非空白且含字母数字时插空格）。不要用简单的 `text == title*2` 判断，只有部分重复时必须按前缀长度切。
- **验收必须看最终 PDF，不看中间 HTML**：单测能证明行高与 HTML 结构，但“两行标题是否压行、页码是否对齐”只在渲染后的 PDF 坐标里成立。因此 e2e 用 PyMuPDF 取文本行与绘制矩形断言；另外用窄页（330pt）探针把长标题逼成两行做目测（`output/v118_wrap_p3.png`）。
- **测量口径的坑**：`toc_anchors` 数量不等于 outline 数量（Systematic：目录 137 条 vs Chromium 书签 305 条），排查“目录页数不对”时先确认用的是哪套锚点，别把两个数字混用。

## 2026-10-20 · v1.1.7：书签回退要用“书的导航”，不要猜样式

- **问题本质**：Chromium 的 `generateDocumentOutline` 只认真实 `h1`–`h6`。InDesign 类 EPUB 用 `<p class="PartStart">` 模拟标题，于是整本只有 1–2 条书签——这不是渲染 bug，是渲染器看不到结构。
- **两条回退路线的取舍**：①按样式/字号猜标题（`p.PartStart`、加粗大字号段落）容易误判，规则无法跨书泛化；②用 EPUB 导航文档（nav/NCX）——它本来就是出版社给的层级，而且**项目已经为生成目录页解析过它**（`NormalizeResult.toc_anchors`，含 level 与 fragment 锚点）。选 ②：零猜测、和目录页同源、页码天然一致。
- **实现要点**：回退必须在**拷贝 Chromium outline 之前**决定。`writer.add_outline_item` 只能追加，先拷再补会出现两套书签；`assembler.assemble` 里先用 `_outline_is_sparse(raw_reader, book)` 判断，再选 `_build_outline_from_toc` 或 `_copy_outline`。阈值用 `max(3, 非封面章数 × 35%)`，避免正常书被导航的浅层结构覆盖。
- **证据**：*Advances in Financial Machine Learning* 6 → 244 条；先前的 `--outline-source ncx` 实验已提示这个方向（当时 244 条/1 层），本轮把它变成“自动且只在需要时触发”。阈值以上不受影响：Systematic 305/4、毛泽东 708/5、Spec 626/3。
- **保留的局限**：若书内导航本身是扁平列表（InDesign 常见），补出来的书签也只有一层——入口齐全但没有章节层级；要真正分层需要出版社提供嵌套 nav，或做标题样式推断（未采纳）。
- **教训（判断与执行）**：先量“书签覆盖率 vs 章节数”再定回退策略；不要用“看起来像标题”的文本启发式替代现成结构数据。

## 2026-10-20 · v1.1.6：页眉 running head 的“像书”规则

- **为什么不能只画一行字**：纸书页眉是“延续页”的标记——章首页/篇首页用大标题，不再重复页眉；目录页不重复“目录”。机械地每页都画会让页面出现重复标题，反而更不像书。实现里用两条规则跳过：①页面顶部最大字号 ≥ 正文 1.12 倍且文本与页眉标签一致 → 章首页；②页面内容顶边（排除 1px 透明锚点块）已经触顶（< 页眉基线 + 字号）→ 固定版式/扫描页。
- **数据源要复用书签锚点**：页眉的章名不能靠“每页重新解析 HTML”，而是复用组装阶段已有的 `{anchor_id: page_index}` 映射，构建 `{页: 章标题}`；这样页眉、书签、目录三者永远指向同一个章节。`title_is_fallback` 的章（标题是文件名/清单 id）不能进页眉，回退书名——否则会印出 `Autopilot_ebook-1`。
- **CJK 字体**：PyMuPDF 内置 `china-s` 可直接 `insert_text`，也可用于 `get_text_length`；不能只依赖 Helvetica（中文会丢字）。页眉截断用 `…`，先测量再删字符。
- **透明锚点会污染几何判断**：`EPBPFANCHOR_*` 的 1px span 在 PyMuPDF 里是真实文本块，`get_text("blocks")` 会把“内容顶边”拉到页面顶部，导致正文页被误判为扫描页而跳过页眉。所有基于“内容位置”的页级判断都必须先过滤含 `EPBPFANCHOR` 的块。
- **验收方式**：e2e 用专门的多页章节 fixture（`longchapter.epub`），断言续页有页眉、章首页与生成目录页没有；再加 `--no-running-headers` 时全空。真实书用“页眉覆盖率”衡量：Systematic 330 页中 297 页有页眉，33 个空页恰好是章首页。

## 2026-10-20 · v1.1.5：原生阅读感三件套（页脚页码 / 稀疏书签 / 语言元数据）

- **页码不能靠 CSS**：Chromium 的 `printToPDF` 不实现 `@page` 的 margin box（`@bottom-center { content: counter(page) }` 被忽略）。可行路径是在组装阶段用 PyMuPDF 给每页写数字：`fitz.open(path)` → `page.insert_text(...)` → `doc.saveIncr()`（原地增量写，不需要重写整本）。页码取**物理页序**，与生成目录页的页码、书签目标页保持一致，避免出现两套编号。封面页跳过编号。
- **稀疏书签要补但不要乱补**：Chromium outline 只从真实 `h1`–`h6` 生成；InDesign 类 EPUB 常用 `<p class="PartStart">` 假标题，整本只有 2 条书签。v1.1.5 在 outline 条目数 < `max(3, 非封面章数×35%)` 时，用章节锚点页补章节级扁平书签（Advances 2→6 条）。阈值很重要：无条件补会让正常书多出一层重复的章条目。
- **元数据也影响“原生感”**：catalog 的 `/Lang`（取 EPUB `dc:language`）和 `/ViewerPreferences /DisplayDocTitle true` 让阅读器窗口显示书名而不是文件名；这两项在 `font_embed` 的 pikepdf 重写后仍保留（已用 `basic.pdf` 验证）。同时把 `<html lang>` 设为书语言，为 Chromium 的断词/读屏提供依据。
- **教训（版本基线）**：做回归对比前先确认对比对象是哪一版代码/数据。v1.1.2 报告里的 Systematic “277 页 / 8.0pt” 不是 v1.1.4 基线；v1.1.4 的 9pt 下限把同一本书变成 330 页 / 8.9pt。拿旧指标当基线会把正常变化误判为回归。
- **教训（验收口径）**：页码、书签这类“阅读感”改动，除单元测试外必须用真实 PDF 断言：页脚数字逐页等于页序、目录页码与书签目标一致、书签覆盖率相对章节数合理。

## 2026-10-20 · v1.1.4：目录页必须“无横线”，点线本身就是问题

- v1.1.3 把点线从列首移到了标题与页码之间，几何上不再压字，但用户仍认为“丑陋的横线没去掉”。复盘：`0.75pt dotted` 在低缩放下会被渲染器/阅读器连成细实线，而读者对目录页的预期是**没有任何装饰线**；只要画线，就存在被当成下划线的观感风险。
- 修法：`toc_page.build_toc_html` 彻底删除 leader（HTML 不输出、CSS 无 `dotted/dashed/border-bottom`），行改为纯 flex：标题（flex:1 + nowrap + ellipsis + 8pt padding）→ 页码固定列。页码仍右对齐、行矩形仍可点击。
- 测试：e2e 断言目录页所有 `height<=1pt 且 width>=3pt` 的绘制数量为 0（`doc[i].get_drawings()`）；重转中文书实测细线绘制 0。
- **教训**：当用户说“像下划线”时，不要只调整线位置/颜色，先确认这条线是否是需求本身；"原生感"通常意味着删掉装饰，而不是美化装饰。

## 2026-10-20 · v1.1.4：字号归一化与绝对 px 适配

- 根因：EPUB 的 `font-size` 以 em 逐级相乘（InDesign 常见 `0.76em` 嵌 `0.71em` → 0.54em ≈ 5.9pt），而 converter 只设定根字号 `html{font-size:...}`，无法阻止子级缩到不可读；另外 `width:500px`/`600px` 容器在窄 auto 页（文本列 ~340pt=453px）会超宽。
- 修法：
  - `normalizer._normalize_font_sizes`：对所有 `font-size` 声明做单位解析（px/pt/em/rem/%/pc/in/cm/mm，`em`/`rem`/`%` 按根字号估算），解析值 < 9pt 时改写为绝对 `9pt`（保留 `!important`；关键词/`calc()` 不处理）。外部样式表与章节内联 `<style>` 都走同一函数。
  - `normalizer._clamp_px_widths`：`width/max-width/min-width` 的 px 值若超过 `layout.text_width_pt`，改为 `min(Npx, 100%)`（`min-width` 置 0）；`<style>` 与元素的 `style="..."` 都处理。
- 验证（auto 默认；排除 1px 透明锚点后统计可见文字）：Systematic 正文众数 8.0→**8.9pt**、Spec 由“24.2% 落在 7.5–8.5pt”变为 **8.9pt / <9pt 占 0.43%**、中文书 9.1pt；Systematic 生成 HTML 有 15 处超宽 px 容器被 clamp。
- **教训**：排版归一化要在“最终 HTML 的 CSS 文本”上做，不能只改根字号；任何字号改写都要有“可读下限”测试 + 真实书字号分布证据，避免把图注/表格差异误伤（只抬低于下限的值）。
- 未能覆盖：扫描版/固定版式 EPUB（Advances）的文本层由 `transform: scale()` 定位，字号与位置来自扫描页，9pt 归一化不适用；这属于固定版式渲染问题。

## 2026-10-20 · v1.1.3：目录页点线压住标题

- 现象：生成的目录页上，每行的点线（dot leader）看起来像整行的下划线，中文书尤其明显；用户截图显示点线从列首贯穿到页码。
- 根因：`toc_page.build_toc_html` 把 `.leader` 做成绝对定位线，`left = 正文列左边界`、`width = 整个标题列宽`，于是点线从标题第一个字的前方就开始了，整个标题都压在线上。
- 修法：行改为 flex（`title` 自适应 → `leader` flex:1 最小 6pt → `page number` 固定列），点线只占标题之后的剩余空隙；标题仍是单行 nowrap + ellipsis。链接矩形沿用整行几何，未受影响。
- 测试：单测断言 leader 不再含 `left:` 且 HTML 顺序为 t→leader→n；e2e 用 PyMuPDF 取 `get_drawings()` 中高度 ≤1pt 的点矩形与所有文字行 bbox 做重叠检测（并集为空）。旧实现能稳定复现 200+ 个重叠点。
- **教训**：目录页这类“文字 + 引导线 + 页码”的布局要用文档流/flex 分配空间，不要用绝对定位 + 估算宽度；视觉元素是否压字应由“几何重叠”测试兜底，而不是只看截图。

## 2026-10-20 · v1.1.2：按封面比例出书 + GUI 显式开始

### 1. EPUB 没有绝对页面尺寸，只能从封面比例推导

- 抽查 10 本 EPUB（testbook/epub、ebook/）的封面像素比：0.665–0.750；同一本书的封面 px 宽高对应的 DPI 不一致（如 790×990 与 790×1008），所以像素尺寸**不能**直接换算成 pt/in。能稳定使用的是**比例**。
- 方案：页面比例取封面比例，页高固定 9.25in（666pt），宽 = 高 × 比例；比例落在 0.58–0.86 之外（横幅、截图、无封面）一律回退 A4 并打 WARNING。与真实印刷版对照（testbook：531×666 / 504×661.5）证明该高度接近纸质书。
- **教训**：EPUB 的 `@page`/`viewport` 只描述阅读器边距，不描述纸张；不要尝试从 EPUB 还原绝对尺寸，把它做成“可推导的比例 + 可控的默认高度”。

### 2. 解析 SVG 尺寸时先定位 `<svg`，不要取第一个 `>`

- `layout._svg_size` 最初用 `text.find(">")` 找开标签结尾，遇到带 `<?xml version="1.0"?>` 声明的封面 SVG 会把声明末尾的 `>` 当起点，导致返回 None（封面尺寸识别失败）。修法：`idx = text.lower().find("<svg")` 后再找 `>`。
- **教训**：图像头解析器要按格式语法找锚点（PNG 固定偏移、JPEG 扫 SOF、SVG 找根元素），不能假设文件没有前置声明/注释。

### 3. GUI “拖入即转换”改“排队 + 开始”后，取消要分两种路径

- 新语义：拖入只入队（行状态 `等待开始`，按钮 `移除`）；点 `开始转换` 才按当前下拉选项逐个提交（并发仍为 1）；运行期间页面尺寸/字号下拉与开始按钮置灰。
- 取消必须区分：`pending` 行 → 从队列删除并移除行；`running` 行 → 走 Orchestrator.cancel。二者共用一个按钮回调，按行状态分派；否则会出现“取消后仍启动”或“取消不掉运行中任务”。
- **教训**：任务队列 UI 要显式建模 `pending/running` 状态，并把“取消”定义成状态函数，而不是单一信号。

### 4. 容错读 EPUB：在临时副本上修，绝不改用户原文件

- 真实案例：`Learning JavaScript Design Patterns` 的 OPF 声明 `OEBPS/toc01.xhtml`（properties=nav），ZIP 里只有 `toc01.html` → ebooklib 直接抛 `There is no item named ...`，整本转换失败。
- 修法：读取失败时把 EPUB 复制到临时目录，按“manifest href 大小写/扩展名唯一匹配”修复后重读；仍失败才报 `EpubParseError`。TOC 章节解析也改为扩展名不敏感（`.html`↔`.xhtml` 按 stem 唯一匹配），否则 nav 存在但生成目录为空。
- **教训**：对“格式合法但实现有瑕疵”的第三方文件，修复应发生在临时副本上，且必须保留“真损坏 → 明确报错”的边界。

## 2026-10-20 · v1.1.0 后：EPUB `@page` 覆盖页边距 / 正文字号偏小

### 1. EPUB 自带的 `@page { margin: 0 }` 会覆盖我们的 A4 页边距（正文贴边）

- **现象**：`Systematic Trading`（InDesign 11.3 导出 EPUB）转出的 PDF，正文从第 7 页起文字贴到纸张四边（第 13 页文本 bbox `x0=0.0, y0=1.3, x1=595.5`；197 个正文页里 193 页左边距 <10pt）。同一程序转《毛泽东选集》《Spec-Driven AI Engineering》正文边距正常（`x0=51–74pt`）。
- **根因（代码核实）**：`normalizer._html5_wrap`（`normalizer.py:542`）的 `<style>` 顺序是 `PRINT_CSS`(`:550`) → 内联 EPUB CSS(`:551`) → `POST_EPUB_CSS`(`:552`)；`_concat_css`(`:564`) 只清 `@charset`，不清 `@page`。该 EPUB 的 `OEBPS/css/idGeneratedStyles.css` 有 `@page { margin: 0px 0px 0px 0px; }`（对自带边距的阅读器合法），同优先级后出现者生效，于是覆盖了 `PRINT_CSS` 的 `@page`；`POST_EPUB_CSS` 又没重新声明 `@page`，没有兜底。
- **Chromium 行为探针**（`preferCSSPageSize: true`）：CSS `@page 18mm` + CDP `margins=0` → bbox `51.0,62.4,541.1`；CSS `@page margin:0` + CDP `margins=0.5in` → bbox `6.0,11.4,589.5`，**margins 参数被完全忽略**。⇒ 边距只能由 CSS 决定，改 CDP 边距参数无效；CLI 回退（`--no-margins`）同样尊重 CSS。
- **教训**：把第三方 CSS 内联进打印文档前，必须清洗会与打印介质冲突的 at-rule（`@page`），并在最后追加自己的 `@page` 兜底；不能假设“我们的 CSS 在前就够”。**状态：v1.1.1 已修复**（`normalizer._strip_at_page_rules` + `POST_EPUB_CSS` 末尾重声明 A4 页边距；`Systematic Trading` 196 个坏页 → 0，见计划 §10 执行记录）。

### 2. 正文偏小主要由 EPUB 的 em 级联字号决定，代码只固定根字号

- `PRINT_CSS` 只设 `html { font-size: 11pt }`（`normalizer.py:65`），不覆盖每段字号；`Spec-Driven AI Engineering` 的 `OEBPS/stylesheet.css`（818 KB）有 **2370 处 `font-size`**，正文类用 em：`class_sH22/sH28` 0.71em（→7.81pt）、`class_sH20` 0.76em、`class_sGUW/sGUY` 0.86em、`class_sH7` 0.95em，嵌套还会相乘。
- PDF 实测（299 页 / 532,563 字符）：≥10.5pt 31.9%、9.5–10.5pt 29.4%、8.5–9.5pt 13.5%、**7.5–8.5pt 24.2%**、<7.5pt 0.9%；该 EPUB 在普通阅读器同样偏小（0.71em×16px≈8.5pt），我们的 11pt 根字号再缩小约 8%。
- **教训**：字号问题先区分“源文件规则”与“转换器固定值”；要改也只能在 CSS 归一化层做（根字号或 `font-size` 下限重写），并配字号断言与视觉回归，属于独立需求。

### 3. 跨版本/跨机器的旧 PDF 不能当作回归基线

- 用户提供的 `Spec-Driven` PDF 是 299 页；用当前代码基线（v1.1.0 `0b04e48`）转同一 EPUB 是 303 页、边距正常。差异来自更早版本或不同机器（字体可用性、Edge 版本影响分页），不是本修复引入。
- **教训**：验收“有没有改坏”必须用“同一代码基线、同一机器”生成对照产物（AGENTS 11.5 控制变量）；用户旧产物只能作为现象样本，不能作为门限。

### 4. PyInstaller 会顺带分析构建机上的无关重型库

- 构建机 site-packages 里装了 torch/tensorflow/cv2/pandas 等，`Analysis` 阶段大量 hook 被触发（构建 >4 分钟，且可能把无关二进制打进包）。`fitz` 已确认解析到 PyMuPDF shim，不是误解析。
- **修法**：在 `EpubToPdf.spec` 的 `Analysis(excludes=[...])` 显式排除这些库与其它 Qt 绑定；它们不是运行期依赖，不影响功能。
- **教训**：打包机与被测环境依赖集不同时，冻结产物要按“声明依赖”显式白名单/黑名单，不能依赖构建机的偶然状态。

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
