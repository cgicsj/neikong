# 本地归档格式

批次根目录保存 `source/名录.json`、批次 `index.html` 和各单位目录；单位目录以单位代码命名，包含 `record.json`、逐题附件目录 `attachments/`、单位 `index.html` 及 `verification.json`。所有 JSON 和 HTML 使用 UTF-8，HTML 应从结构化数据生成，不拼接未经转义的浏览器 HTML。

## 数据结构

- 名录顶层包含 `task`、`total`、`page_size`、`columns` 和 `rows`。每行保留 `page`、`code`、`name`、`cells`、`eligible` 和 `has_detail`。
- `record.json` 保存 `unit_code`、`unit_name`、`captured_at`、`basic`、`score_summary`、`expected_items`、`indicator_plan`、`items`、`supplementary` 和 `issues`。基本信息按分组 `title`、表格 `rows` 保存。
- 评价项目保存 `order`、`title`、`group`、系统显示的 `score` 和 `fields`。标题层级用 `heading`，指标题干用 `label`，评分题的实际得分用 `answers`。适用性题保存 `kind: "applicability"` 和 `applicability`（`"适用"`、`"不适用"` 或待核对的 `null`）。未能识别题型时保存 `kind: "unclassified"`。上传项仅登记在评价指标明细内，保存 `kind: "attachment"`、`attachments` 和 `list_confirmed`。
- 附件记录保存门户文件名 `name`、弹窗页码 `page`、可见行信息 `metadata`、本地文件大小 `size`、本地相对路径 `path`、`sha256`、页码/内容单元 `content_units`、逐页 `text_parts` 及实际 `status`。印章信息以 `seal_status` 和 `seals` 保存。
- `supplementary` 保存「补充说明」页实际读取的文本、表格和字段值；对明确空白记录空状态，不推测补写。无法确认页面内容时写入 `issues`。

## HTML 内容

- 单位明细只能包含「基本信息」「评价指标打分」「补充说明」三部分，不生成系统报告文档，也不把导出的报告压缩包作为交付物。
- 评价打分正文按四个大类、子项目和指标题干分层。项目最终得分优先采用复核分，其次采用评价分。评分题显示实际分值并保留 0 分，未取得分值时显示「指标得分：未取得」并记录问题。适用性题显示「适用性：适用」或「适用性：不适用」。旧归档缺少适用性选择时显示「适用性：待核对」，确认原系统选择后再补录。
- 逐题附件链接和 OCR 文字归属于对应评价指标，纯文字直接显示。只显示盖章情况、盖章单位、与填报单位是否一致，不加其他附件分析。
- 批次 HTML 只列出开展评价且有明细入口的单位，以单位名称链接到明细。采集状态列紧跟单位名称；不显示单位代码、标记、复核得分、复核结果认定和上报日期。
- `verification.json` 记录三部分是否采齐、项目数是否与目录一致、附件清单/原件/OCR 覆盖是否完成，以及所有缺项。只有三部分及适用的逐题附件均完成核对且 HTML 链接有效，才标记「校验通过」。

运行生成器：

```text
python -X utf8 scripts/build_archive.py "批次目录"
```

独立复核数据保存为单位目录下 `source/portal-check.json`，记录复核开始时间和同范围中可见的网页内容。 `source/portal-attempt.json` 标明最近一次尝试是否完成。 `verification.json` 的 `generated_at` 表示本地记录生成时间。生成器比对归档记录与复核记录，并核对附件路径、哈希和 OCR 覆盖；差异保存在本地 `verification.json`。
