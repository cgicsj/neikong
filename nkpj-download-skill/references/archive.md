# 本地归档格式

批次根目录保存 `source/名录.json` 及批次 `index.html`，每个已采单位使用单位代码命名子目录。用 UTF-8 保存，不要拼接未转义的浏览器 HTML。生成器根据数据重建基本信息表格、评分导航和题目内容。

- 名录顶层包含 `task`、`total`、`page_size`、`columns` 和 `rows`。每行保留 `page`、`code`、`name`、`cells`、`eligible` 和 `has_detail`。
- 单位 `record.json` 包含 `unit_code`、`unit_name`、`captured_at`、`basic`、`score_summary`、`expected_items`、`indicator_plan`、`items`、`issues`。`indicator_plan` 保存四个大类的实际子项目序列，每项含 `group` 和 `title`。基本信息各组用 `title` 和 `rows` 表示，每个单元格有 `text`，表单值另存 `value`，可用 `colspan`、`rowspan` 保留合并。
- 每个指标项目含 `order`、`title`、界面显示的 `score`、可选 `group` 和 `fields`。标题项用 `heading`，指标题干用 `label`，省去开头的必填星号，`answers` 只记录实际评分。上传项用 `kind: "attachment"`、`label: "附件"`、`attachments` 和 `list_confirmed` 表示，清单确认后设为 `true`。保留每个上传入口的顺序和原件归属。
- 每条附件登记至少记录 `name`，确认原件后写入 `path`（如 `attachments/001-材料.pdf`）、`sha256`、`content_units` 和 `text_parts`。每段写 `location`、`method`、`text`。缺失或尚未识读的附件保留实际状态 `status`，并在 `issues` 中注明题目和原因。
- 印章用 `seal_status` 和 `seals` 保存。状态使用「有可辨识印章」「有章但单位待复核」「未见印章」或「无法判断」。`seals` 中每枚章保存 `location`、`organization`（印面可确认的单位全称，无法确认时写「待复核」）及可辨印面文字 `inscription`。识读正文与印章检查信息分别保存。

## HTML 显示

- 批次保留完整源名录，汇总表只展示操作列有「更多」的单位。汇总表省略「单位代码」「标记」「复核得分」「复核结果认定」「上报日期」列，「采集状态」紧跟「单位名称」。单位名称是明细入口，未采集的入口显示当前状态。
- 明细的导航和正文依次展示四个大类、其下评价项目和实际指标。大类下没有已采集项目时显示「尚未采集」。项目最终得分优先采用该项目的复核分，复核分尚未显示时采用评价分，两者都缺失时显示「—」。每条指标显示同题评分控件实际选中的分值，保留「0分」，缺失时显示「未取得」并记入校验记录。已确认的空清单显示「未上传」，读取失败显示「附件清单待核」，缺少确认记录的旧档显示「无附件记录」。
- 附件正文按页直接显示，识读方式和成功状态保存在数据记录。盖章检测显示「盖章情况」「盖章单位」「与填报单位是否一致」，同名比对时允许省略填报单位名称末尾的「（本级）」。

```text
python -X utf8 scripts/build_archive.py "批次目录"
```

独立复读时用同一记录结构保存到单位目录的 `source/portal-check.json`，`captured_at` 记录实际复核时点，附件保留网页原名。生成脚本将该记录与归档的网页字段及附件名比对，并检查原件路径、哈希和识读覆盖，输出 `verification.json`。OCR 和原件内容核验由执行采集的 Agent 完成。
