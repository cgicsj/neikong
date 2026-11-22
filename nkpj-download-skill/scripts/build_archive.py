"""Build offline evaluation materials and reconcile recorded files."""

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from urllib.parse import quote


CSS = """
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#263449;font:15px/1.7 "Microsoft YaHei",sans-serif}
header{background:#15365b;color:white;padding:.85rem max(1rem,calc((100vw - 1240px)/2))}
header h1{font-size:1.25rem;margin:0}header small{color:#e2eaf5}main{max-width:1280px;margin:auto;padding:1.2rem}
nav{display:flex;gap:1.25rem;flex-wrap:wrap;margin-bottom:1rem}a{color:#16588e}a:focus{outline:2px solid #16588e}
.card,article,aside{background:white;border:1px solid #dce3ed;border-radius:7px;padding:1rem}
.card{margin-bottom:1rem}article{margin-bottom:1rem}h2,h3,h4,h5{line-height:1.45;margin:0 0 .65rem}
h2{font-size:1.17rem}h3{font-size:1.05rem}h4,h5{font-size:1rem}.table-wrap{overflow:auto}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #dce3ed;text-align:left;padding:.42rem .65rem;vertical-align:top}
th{background:#eaf0f7}td.value{background:#f6f8fa;white-space:pre-wrap}.layout{display:grid;grid-template-columns:15rem minmax(0,1fr);gap:1rem;align-items:start}
aside{position:sticky;top:1rem;max-height:90vh;overflow:auto}aside ul{margin:0;padding-left:1.25rem}aside a{display:block}
.score,.field{white-space:pre-wrap;overflow-wrap:anywhere}.score{color:#476581;background:#f0f5fb;padding:.55rem .7rem;margin:0 0 1rem}
.field{padding:.65rem 0;border-top:1px solid #e1e7f0}
.indicator-score{display:block;margin-top:.2rem;color:#31577a}
.attachment{border-left:3px solid #b6cbe1;padding:.3rem .6rem;margin:.35rem 0}.notice{color:#596b81}
.seal{margin:.4rem 0}.attachment-text{white-space:pre-wrap;margin:.35rem 0 .8rem}
.supplementary-text{white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:720px){.layout{grid-template-columns:1fr}aside{position:static;max-height:none}}
"""


def text(value):
    return escape(str(value), quote=True)


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


def write_html(path, title, meta, body):
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{text(title)}</title><style>{CSS}</style></head><body>'
            f'<header><h1>{text(title)}</h1><small>{text(meta)}</small></header>'
            f'<main>{body}</main></body></html>')
    path.write_bytes(page.encode("utf-8"))


READING_COMPLETE = {"识读完成", "全文已提取"}
SEAL_STATES = {"有可辨识印章", "有章但单位待复核", "未见印章", "无法判断"}
SCORE_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
GROUP_TITLES = ("一、组织层面内部控制", "二、业务层面内部控制", "三、内部监督", "四、补充指标")
LEGACY_ORGANIZATION = {"议事决策机制", "内部权力运行", "组织架构", "财务信息", "信息化"}


def item_group(item):
    if item.get("group"):
        return item["group"]
    title = re.sub(r"^[（(][一二三四五六七八九十]+[）)]\s*", "", item["title"])
    return GROUP_TITLES[0] if title in LEGACY_ORGANIZATION else "待确认所属大类"


def complete_indicators(document):
    items = document.get("items", [])
    count = document.get("expected_items")
    plan = document.get("indicator_plan", [])
    actual = [{"group": item_group(item), "title": item["title"]} for item in items]
    return bool(count and len(items) == count and actual == plan
                and len({(item["group"], item["title"]) for item in actual}) == count
                and list(dict.fromkeys(item["group"] for item in actual)) == list(GROUP_TITLES)
                and [item["order"] for item in items] == list(range(1, count + 1)))


def normalized_name(value):
    return "".join(unicodedata.normalize("NFKC", value).split())


def seal_html(item, unit_name, location, issues):
    status = item.get("seal_status")
    names = list(dict.fromkeys(seal.get("organization", "").strip() for seal in item.get("seals", [])))
    if (status not in SEAL_STATES or status == "未见印章" and names
            or status == "有可辨识印章" and not names):
        issues.append(f"{location} / {item['name']}：缺少可靠的印章检查记录")
        status = "无法判断"
        names = []
    elif status in {"有章但单位待复核", "无法判断"}:
        issues.append(f"{location} / {item['name']}：印章待复核")
    target = normalized_name(unit_name)
    organizations = []
    matches = []
    for name in names:
        if normalized_name(name) in {"", "待复核", "无法判断", "辨认不清"}:
            organizations.append("无法判断")
            matches.append("无法判断")
            issues.append(f"{location} / {item['name']}：盖章单位待复核")
        else:
            organizations.append(name)
            matches.append("一致" if normalized_name(name) in {target, target.removesuffix("(本级)")} else "不一致")
    if not names:
        organizations.append("—" if status == "未见印章" else "无法判断")
        matches.append("不适用" if status == "未见印章" else "无法判断")
    return (f'<div class="seal">盖章情况：{text(status)}<br>'
            f'盖章单位：{text("；".join(organizations))}<br>'
            f'与填报单位是否一致：{text("；".join(matches))}</div>')


def attachment_html(item, folder, unit_name, location, issues):
    name = text(item["name"])
    raw_path = item.get("path", "")
    if raw_path:
        relative = PurePosixPath(raw_path)
        original = folder.joinpath(*relative.parts).resolve()
        if (relative.parts[:1] != ("attachments",) or ".." in relative.parts or "\\" in raw_path
                or ":" in raw_path or not original.is_relative_to(folder / "attachments")
                or not original.is_file() or not original.stat().st_size):
            issues.append(f"{location} / {item['name']}：原件路径无效或文件为空")
        else:
            with original.open("rb") as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != str(item.get("sha256", "")).lower():
                issues.append(f"{location} / {item['name']}：原件哈希缺失或不一致")
            name = f'<a href="{quote(relative.as_posix(), safe="/")}">{name}</a>'
    else:
        issues.append(f"{location} / {item['name']}：{item.get('status', '原件待下载')}")
    parts = item.get("text_parts", [])
    if raw_path and (not item.get("content_units")
                     or item["content_units"] != [part["location"] for part in parts]
                     or any(not part.get("text") and not part.get("blank") for part in parts)
                     or item.get("status") not in READING_COMPLETE):
        issues.append(f"{location} / {item['name']}：{item.get('status', '识读覆盖待确认')}")
    status = item.get("status", "")
    notice = f' <span class="notice">{text(status)}</span>' if status and status not in READING_COMPLETE else ""
    seals = seal_html(item, unit_name, location, issues)
    readings = "".join(f'<div>{text(part["location"])}</div>'
                       f'<p class="attachment-text">{text(part.get("text", ""))}</p>' for part in parts)
    return f'<div class="attachment">{name}{notice}{seals}{readings}</div>'


def basic_table(group):
    rows = []
    for row in group["rows"]:
        columns = []
        for cell in row:
            value = cell.get("value")
            attrs = f' colspan="{int(cell.get("colspan", 1))}" rowspan="{int(cell.get("rowspan", 1))}"'
            tag, css = ("td", ' class="value"') if value is not None else ("th", "")
            columns.append(f'<{tag}{attrs}{css}>{text(cell["text"] if value is None else value)}</{tag}>')
        rows.append("<tr>" + "".join(columns) + "</tr>")
    return f'<h3>{text(group["title"])}</h3><div class="table-wrap"><table>' + "".join(rows) + "</table></div>"


def supplementary_html(data, issues):
    if not data or data.get("confirmed") is not True:
        issues.append("补充说明未确认采集")
        return '<p class="notice">补充说明尚未采集或待核</p>'
    parts = []
    if data.get("text"):
        parts.append(f'<div class="supplementary-text">{text(data["text"])}</div>')
    for index, rows in enumerate(data.get("tables", []), 1):
        rendered = []
        for row in rows:
            cells = []
            for cell in row:
                tag = "td" if cell.get("value") is not None else "th"
                value = cell.get("value") if cell.get("value") is not None else cell.get("text", "")
                attrs = f' colspan="{int(cell.get("colspan", 1))}" rowspan="{int(cell.get("rowspan", 1))}"'
                cells.append(f'<{tag}{attrs}>{text(value)}</{tag}>')
            rendered.append("<tr>" + "".join(cells) + "</tr>")
        parts.append(f'<div class="table-wrap"><table>{"".join(rendered)}</table></div>')
    for field in data.get("fields", []):
        label, value = field.get("label", ""), field.get("value", "")
        if label or value:
            parts.append(f'<p><strong>{text(label)}</strong> {text(value)}</p>')
    if not parts:
        parts.append('<p class="notice">页面已确认，未显示补充说明内容。</p>')
    return "".join(parts)


def final_score(section):
    # The portal score row ends in the columns 总分、评价、复核, in that order.
    raw = section.get("score") or ""
    _, separator, tail = raw.rpartition(section["title"])
    scores = tail.split() if separator else []
    if len(scores) not in {2, 3} or any(not re.fullmatch(SCORE_NUMBER + r"|[-—]+", score) for score in scores):
        return "—"
    return next((score for score in reversed(scores[1:]) if re.fullmatch(SCORE_NUMBER, score)), "—")


def indicator_label(raw):
    raw = re.sub(r"^\s*[*＊]\s*", "", raw)
    # Older captures flattened the gray scoring guidance into the label.
    lines = raw.splitlines()
    has_stem = False
    for index, line in enumerate(lines):
        if has_stem and re.search(r"不扣分|扣\s*\d+(?:\.\d+)?\s*分", line):
            return "\n".join(lines[:index]).rstrip()
        if line.strip():
            has_stem = True
    return raw


def indicator_field(field):
    if "heading" in field:
        return {"heading": re.sub(r"^\s*[*＊]\s*", "", field["heading"])}
    legacy_upload = ("attachments" in field and not field.get("answers") and "display" not in field)
    if field.get("kind") == "attachment" or legacy_upload:
        return {"kind": "attachment", "label": "附件", "attachments": field.get("attachments", []),
                "list_confirmed": field.get("list_confirmed")}
    scores = []
    for answer in field.get("answers", []):
        label = answer.get("label", "").strip()
        value = str(answer.get("value", ""))
        if (answer.get("selected") and re.fullmatch(SCORE_NUMBER + r"\s*分", label)
                or re.fullmatch(SCORE_NUMBER + r"\s*分", value)
                or (re.search(r"得分|评分|分值", label) and re.fullmatch(SCORE_NUMBER, value))):
            scores.append(answer)
    return {"label": indicator_label(field["label"]), "answers": scores}


def evaluation_item(section, folder, unit_name, issues):
    questions = []
    upload_number = 0
    for original in section["fields"]:
        field = indicator_field(original)
        if "heading" in field:
            questions.append(f'<h5 class="field">{text(field["heading"])}</h5>')
            continue
        label = field["label"]
        location = f"{section['title']} / {label}"
        if field.get("kind") == "attachment":
            upload_number += 1
            location = f"{section['title']} / 第{upload_number}处附件"
            if field["list_confirmed"] is not True:
                issues.append(f"{location}：附件清单待核")
            attachments = "".join(attachment_html(a, folder, unit_name, location, issues) for a in field["attachments"])
            if not attachments:
                status = "未上传" if field["list_confirmed"] else "无附件记录"
                if field["list_confirmed"] is False:
                    status = "附件清单待核"
                attachments = f'<span class="notice">　{text(status)}</span>'
            content = attachments
        else:
            values = []
            for answer in field["answers"]:
                value = str(answer.get("value", answer.get("label", ""))).strip()
                values.append(value if value.endswith("分") else f"{value}分")
            if not values:
                issues.append(f"{location}：未取得指标得分")
            content = f'<span class="indicator-score">指标得分：{text("；".join(values) or "未取得")}</span>'
        questions.append(f'<div class="field"><strong>{text(label)}</strong>{content}</div>')
    return (f'<article id="item-{section["order"]}"><h4>{text(section["title"])}</h4>'
            f'<div class="score">最终得分：{text(final_score(section))}</div>{"".join(questions)}</article>')


def grouped_indicators(items, folder, unit_name, issues):
    grouped = {title: [] for title in GROUP_TITLES}
    for item in items:
        grouped.setdefault(item_group(item), []).append(item)
    menu, body = [], []
    for number, (title, projects) in enumerate(grouped.items(), 1):
        anchor = f"group-{number}"
        children = "".join(f'<li><a href="#item-{item["order"]}">{text(item["title"])}</a></li>'
                           for item in projects)
        subnav = f"<ul>{children}</ul>" if children else ""
        menu.append(f'<li><a href="#{anchor}">{text(title)}</a>{subnav}</li>')
        detail = ("".join(evaluation_item(item, folder, unit_name, issues) for item in projects)
                  or '<p class="card notice">尚未采集</p>')
        body.append(f'<section id="{anchor}"><h3 class="card">{text(title)}</h3>'
                    f'{detail}</section>')
    return "".join(menu), "".join(body)


def portal_fields(document):
    items = []
    for item in document.get("items", []):
        fields = []
        for original in item["fields"]:
            field = indicator_field(original)
            if "attachments" in field:
                field["attachments"] = [attachment["name"] for attachment in field["attachments"]]
                field.pop("list_confirmed")
            fields.append(field)
        items.append({**item, "fields": fields})
    supplementary = document.get("supplementary")
    if isinstance(supplementary, dict):
        supplementary = {key: value for key, value in supplementary.items() if key != "captured_at"}
    keys = ("unit_code", "unit_name", "report_version", "basic", "score_summary", "expected_items", "indicator_plan", "supplementary")
    return (*[supplementary if key == "supplementary" else document.get(key) for key in keys], items)


def verify_source(folder, document, issues):
    snapshot = folder / "source" / "portal-check.json"
    if not snapshot.is_file():
        issues.append("独立网页复核尚未完成")
        return
    try:
        checked = load(snapshot)
        first = datetime.fromisoformat(document["captured_at"].replace("Z", "+00:00"))
        last = datetime.fromisoformat(checked["captured_at"].replace("Z", "+00:00"))
        if first.utcoffset() is None or last.utcoffset() is None or last < first:
            issues.append("网页复核时间无效或早于采集时间")
        if checked.get("issues") or portal_fields(checked) != portal_fields(document):
            issues.append("独立网页复核记录有缺项或与归档内容不一致")
        if any(field.get("kind") == "attachment" and field["list_confirmed"] is not True
               for item in checked["items"] for field in map(indicator_field, item["fields"])):
            issues.append("独立网页复核存在未确认的附件清单")
    except (OSError, TypeError, KeyError, ValueError) as error:
        issues.append(f"独立网页复核记录无法读取：{error}")


def build_unit(folder, row, task):
    doc = load(folder / "record.json")
    issues = list(doc.get("issues", []))
    if (doc.get("unit_code"), doc.get("unit_name")) != (row["code"], row["name"]):
        raise ValueError(f"{folder.name}：归档主体与名录不一致")
    if not doc.get("basic"):
        issues.append("基本信息未采集")
    if not doc.get("supplementary", {}).get("confirmed"):
        issues.append("补充说明未采集或未确认")
    sections = doc.get("items", [])
    if not complete_indicators(doc):
        issues.append("评价项目尚未按系统目录完成四个大类的对账")
    verify_source(folder, doc, issues)
    menu, body = grouped_indicators(sections, folder, row["name"], issues)
    supplementary = supplementary_html(doc.get("supplementary"), issues)
    issues = list(dict.fromkeys(issues))
    status = "待复核" if issues else "校验通过"
    basics = "".join(basic_table(group) for group in doc.get("basic", []))
    upload_fields = [indicator_field(field) for item in sections for field in item.get("fields", [])]
    upload_fields = [field for field in upload_fields if field.get("kind") == "attachment"]
    attachments = [attachment for field in upload_fields for attachment in field.get("attachments", [])]
    write_html(folder / "index.html", row["name"], f"{task} · {row['code']}",
               '<nav><a href="../index.html">批次名录</a><a href="#basic">基本信息</a>'
               '<a href="#scores">评价指标打分</a><a href="#supplementary">补充说明</a></nav>'
               f'<section class="card" id="basic"><h2>基本信息</h2>{basics}</section>'
               f'<section class="card" id="scores"><h2>评价指标打分</h2>'
               f'<div class="layout"><aside><strong>评价项目</strong><ul>{menu}</ul></aside><div>{body}</div></div></section>'
               f'<section class="card" id="supplementary"><h2>补充说明</h2>{supplementary}</section>')
    write_json(folder / "verification.json",
               {"status": status, "verified_at": datetime.now(timezone.utc).isoformat(),
                "coverage": {"basic_information": bool(doc.get("basic")),
                             "evaluation_projects": {"complete": complete_indicators(doc),
                                                     "expected": doc.get("expected_items"),
                                                     "captured": len(sections)},
                             "supplementary": bool(doc.get("supplementary", {}).get("confirmed")),
                             "scoring_page_attachments": {"listed": len(attachments),
                                                          "downloaded": sum(bool(item.get("path")) for item in attachments),
                                                          "ocr_complete": sum(item.get("status") in READING_COMPLETE
                                                                              for item in attachments)}},
                "issues": issues})
    return status


def build_batch(root):
    manifest = load(root / "source" / "名录.json")
    rows = manifest["rows"]
    if len(rows) != manifest["total"] or len({row["code"] for row in rows}) != len(rows):
        raise ValueError("名单数量不一致或存在重复单位代码")
    totals = {}
    body = []
    source_columns = manifest["columns"]
    name_index = source_columns.index("单位名称")
    hidden_columns = {"单位代码", "标记", "复核得分", "复核结果认定", "上报日期"}
    visible_columns = [(index, name) for index, name in enumerate(source_columns[1:-1], 1)
                       if name not in hidden_columns]
    name_column = next(position for position, (index, _) in enumerate(visible_columns)
                       if index == name_index)
    columns = [name for _, name in visible_columns]
    columns.insert(name_column + 1, "采集状态")
    eligible = [row for row in rows if row["eligible"]]
    for row in eligible:
        code = row["code"]
        if Path(code).name != code or not code.isalnum():
            raise ValueError(f"无法安全建立单位目录：{code}")
        folder = root / code
        if (folder / "record.json").is_file():
            status = build_unit(folder, row, manifest["task"])
        else:
            status = "未采集" if row["has_detail"] else "待复核（无明细入口）"
            folder.mkdir(exist_ok=True)
            write_html(folder / "index.html", row["name"], f"{manifest['task']} · {code}",
                       '<nav><a href="../index.html">批次名录</a></nav>'
                       f'<p class="card">{text(status)}，暂无明细可查看。</p>')
        totals[status] = totals.get(status, 0) + 1
        cells = [text(row["cells"][index]) for index, _ in visible_columns]
        cells[name_column] = f'<a href="{quote(code)}/index.html">{text(row["name"])}</a>'
        cells.insert(name_column + 1, text(status))
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    headings = "".join(f"<th>{text(name)}</th>" for name in columns)
    info = " · ".join(f"{status} {count} 家" for status, count in totals.items())
    write_html(root / "index.html", manifest["task"] + "批次归档",
               f"开展评价 {len(eligible)} 家" + (f" · {info}" if info else ""),
               f'<div class="table-wrap"><table><thead><tr>{headings}</tr>'
               f'</thead><tbody>{"".join(body)}</tbody></table></div>')
    return totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    print(json.dumps(build_batch(parser.parse_args().batch.resolve()), ensure_ascii=False))
