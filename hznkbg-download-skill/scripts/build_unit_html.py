"""Build an offline HTML report from one unit's collected record and attachments."""

import argparse
from html import escape
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from urllib.parse import quote


SEAL_STATES = {"有可辨识印章", "有章但单位待复核", "未见印章", "无法判断"}
CONFIRMED_DOWNLOADS = {"已下载", "已下载并与清单核对"}
TEXT_PROBLEM_MARKERS = ("失败", "无法", "不完整", "缺页", "未完成", "未读完", "异常", "待补")
SEAL_DESIGNATIONS = ("公章", "印章", "财务专用章", "合同专用章", "发票专用章")
SEAL_SUFFIXES = {"", *SEAL_DESIGNATIONS, *(f"({word})" for word in SEAL_DESIGNATIONS)}
CSS = """
* { box-sizing: border-box; }
body { max-width: 72rem; margin: 0 auto; padding: 2rem 1.25rem; color: #172d32;
       background: #f4f7f6; font: 16px/1.65 "Microsoft YaHei", sans-serif; }
h1, h2, h3, h4, h5, h6 { line-height: 1.4; overflow-wrap: anywhere; }
h1 { font-size: clamp(1.45rem, 4vw, 2rem); margin: 0; }
header { padding: .4rem 0 1.1rem; }
.meta { color: #4d666c; }
header p { margin: .35rem 0 0; }
.report-nav { position: sticky; top: 0; z-index: 1; display: flex; flex-wrap: wrap;
              gap: .4rem; padding: .55rem 0; background: #f4f7f6; border-bottom: 1px solid #c9d8d5; }
.report-nav a { padding: .3rem .65rem; border-radius: .3rem; font-weight: 600; }
.report-nav a:hover, .report-nav a:focus-visible { background: #deece7; }
.report-section { margin: 1.25rem 0; padding: clamp(.8rem, 3vw, 1.5rem);
                  border: 1px solid #c9d8d5; border-radius: .55rem; background: white; scroll-margin-top: 6rem; }
.report-section > h2 { margin: 0 0 .85rem; font-size: 1.3rem; }
.form-group { min-width: 0; margin: 1rem 0; }
.group-title { margin: 0 0 .45rem; padding: .45rem .65rem;
               background: #e5f0ec; font-size: 1rem; }
.form-group .form-group > .group-title { margin-top: .9rem; background: #f1f6f4; }
.form-group .form-group .form-group > .group-title { border-bottom: 1px solid #d8e4e1; background: white; }
.field { min-width: 0; padding: .65rem; border-bottom: 1px solid #e0e9e7; }
.field-title { margin: 0 0 .2rem; font-size: .93rem; font-weight: 600; }
.basic-info > .form-group { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.basic-info > .form-group > :not(.field), .basic-info > .form-group > .has-attachments { grid-column: 1 / -1; }
.value, .text { white-space: pre-wrap; overflow-wrap: anywhere; }
.value { margin: 0; }
.attachment { border-left: 3px solid #90ada6; background: #f5f8f7;
              padding: .55rem .8rem; margin-top: .55rem; overflow-wrap: anywhere; }
.attachment-name { margin: 0; font-weight: 600; }
.attachment > p { margin-block: .35rem; }
.attachment-text { margin-top: .65rem; border-top: 1px solid #d8e4e1; }
.attachment-text > p { margin-block: .55rem; }
.attachment-text > .meta { font-size: .9rem; }
a { color: #175c56; }
@media (max-width: 48rem) {
  .basic-info > .form-group { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 33rem) {
  body { padding: 1rem .65rem; }
  .basic-info > .form-group { grid-template-columns: minmax(0, 1fr); }
}
@media print {
  body, .report-section { padding: 0; background: white; }
  .report-nav { display: none; }
  .report-section { border: 0; }
  h2, .group-title, .field-title { break-after: avoid; }
}
"""


def text(value):
    return escape(str(value), quote=True)


def original_link(directory, raw_path):
    path = PurePosixPath(raw_path)
    if (len(path.parts) < 2 or path.parts[0] != "attachments"
            or ".." in path.parts or "\\" in raw_path or ":" in raw_path):
        raise ValueError(f"附件须在 attachments/ 目录内：{raw_path}")
    original = directory.joinpath(*path.parts).resolve()
    if (not original.is_relative_to(directory / "attachments")
            or not original.is_file() or original.stat().st_size == 0):
        raise ValueError(f"附件不存在、为空或超出归档目录：{raw_path}")
    return quote(path.as_posix(), safe="/")


def normalize_unit_name(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))


def compare_seal(seal, unit_name):
    name = normalize_unit_name(seal.get("organization") or "")
    # Older records separate the circular and center text with a slash.
    inscription = normalize_unit_name(seal.get("inscription") or "").replace("/", "")
    reported = normalize_unit_name(unit_name)
    if not reported or name in {"", "待复核", "无法判断", "不明", "未识别"}:
        return "无法判断"
    if not inscription.startswith(name):
        return "无法判断"
    suffix = re.sub(r"(?:\([0-9]+\)|\[[0-9]+\]|[0-9]+)$", "", inscription[len(name):])
    if suffix not in SEAL_SUFFIXES:
        return "无法判断"
    return "一致" if name in {reported, reported.removesuffix("(本级)")} else "不一致"


def render_seal_summary(item, unit_name):
    status = item["seal_status"]
    if status not in SEAL_STATES:
        raise ValueError(f"无效的盖章状态：{status}")

    entries = []
    for seal in item.get("seals", []):
        result = compare_seal(seal, unit_name)
        organization = seal["organization"] if result != "无法判断" else "无法判断"
        entries.append((organization, result))
    if not entries:
        entries.append(("—", "不适用") if status == "未见印章" else ("无法判断", "无法判断"))

    organizations, results = zip(*dict.fromkeys(entries))
    return (
        f"<p>盖章情况：{text(status)}</p>"
        f"<p>盖章单位：{text('；'.join(organizations))}</p>"
        f"<p>与填报单位是否一致：{text('；'.join(results))}</p>"
    )


def render_attachment(item, directory, unit_name):
    name = text(item["name"])
    if item.get("path"):
        href = original_link(directory, item["path"])
        name = f'<a href="{text(href)}">{name}</a>'
    parts = "".join(
        f"<p class='meta'>{text(part['location'])}</p>"
        f"<p class='text'>{text(part['text'])}</p>"
        for part in item.get("text_parts", [])
    )
    text_status = item["text_status"]
    show_status = (
        not parts
        or any(marker in text_status for marker in TEXT_PROBLEM_MARKERS)
    )
    status = f"<p class='meta'>识读状态：{text(text_status)}</p>" if show_status else ""
    full_text = (
        "<div class='attachment-text'>"
        f"<p><strong>附件全文</strong></p>{status}{parts}</div>"
    )
    download = ""
    if not item.get("path") or item["download_status"] not in CONFIRMED_DOWNLOADS:
        download = f"<p>下载状态：{text(item['download_status'])}</p>"
    return (
        f"<div class='attachment'><p class='attachment-name'>{name}</p>"
        f"{download}"
        f"{render_seal_summary(item, unit_name)}{full_text}</div>"
    )


def render_field(field, directory, unit_name, heading_level):
    value = field.get("value")
    if isinstance(value, list):
        value = "\n".join(map(str, value)) if value else "未选"
    if value == "":
        value = "空白"
    answer = "" if value is None else f"<p class='value'>{text(value)}</p>"
    attachments = "".join(
        render_attachment(item, directory, unit_name) for item in field.get("attachments", [])
    )
    field_class = "field has-attachments" if attachments else "field"
    heading = f"h{min(heading_level, 6)}"
    return (
        f"<article class='{field_class}'><{heading} class='field-title'>{text(field['label'])}</{heading}>"
        f"{answer}{attachments}</article>"
    )


def render_fields(fields, directory, unit_name):
    content = []
    opened = []
    for index, field in enumerate(fields):
        path = field.get("path", [])
        next_path = fields[index + 1].get("path", []) if index + 1 < len(fields) else []
        # A separately stored heading is rendered by the group it introduces.
        if (field.get("value") is None and not field.get("attachments")
                and next_path[:len(path) + 1] == [*path, field["label"]]):
            continue

        shared = 0
        for current, target in zip(opened, path):
            if current != target:
                break
            shared += 1
        content.extend("</div>" for _ in opened[shared:])
        for depth, label in enumerate(path[shared:], start=shared):
            heading = f"h{min(depth + 3, 6)}"
            content.append(f"<div class='form-group'><{heading} class='group-title'>{text(label)}</{heading}>")
        opened = path
        content.append(render_field(field, directory, unit_name, len(path) + 3))
    content.extend("</div>" for _ in opened)
    return "".join(content)


def render_record(record, directory):
    title = f"{record['year']}年度内控编报 · {record['unit_name']}"
    navigation = "".join(
        f"<a href='#section-{index}'>{text(section['title'])}</a>"
        for index, section in enumerate(record["sections"], 1)
    )
    sections = "".join(
        f"<section id='section-{index}' class='report-section"
        + (" basic-info" if section["title"] == "基本信息录入" else "")
        + f"'><h2>{text(section['title'])}</h2>"
        + (f"<p class='meta'>{text(section['status'])}</p>" if section["status"] != "已采集" else "")
        + render_fields(section["fields"], directory, record["unit_name"])
        + "</section>"
        for index, section in enumerate(record["sections"], 1)
    )
    issues = "".join(f"<li>{text(issue)}</li>" for issue in record.get("issues", []))
    issues_section = f"<section class='report-section'><h2>采集缺项</h2><ul>{issues}</ul></section>" if issues else ""
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{text(title)}</title><style>{CSS}</style></head><body>"
        f"<header><h1>{text(record['unit_name'])}</h1><p class='meta'>"
        f"{text(record['year'])}年度内控编报 · "
        f"{text(record['unit_code'])} · {text(record['entity_type'])} · "
        f"采集时间 {text(record['captured_at'])}</p></header>"
        f"<nav class='report-nav' aria-label='填报页签'>{navigation}</nav>"
        f"<main>{sections}{issues_section}</main></body></html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    record_path = parser.parse_args().record.resolve()
    record = json.loads(record_path.read_text(encoding="utf-8-sig"))
    output = record_path.with_name("index.html")
    rendered = render_record(record, record_path.parent)
    output.write_text(rendered, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
