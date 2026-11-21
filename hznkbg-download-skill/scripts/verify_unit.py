"""Reconcile one archive against a separately captured portal snapshot."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from build_unit_html import CONFIRMED_DOWNLOADS, compare_seal, original_link, render_record


IDENTITY = ("year", "unit_name", "unit_code", "entity_type", "report_version")
EXPECTED_ENTITY = "汇总部门"
EXPECTED_TABS = ["基本信息录入", "部门内部控制情况"]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"JSON 不支持非有限数值：{value}")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"),
                          object_pairs_hook=unique_object, parse_constant=reject_constant)
    except ValueError as error:
        raise ValueError(f"{path.name}：{error}") from error


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def valid_value(value):
    if isinstance(value, list):
        return all(nonempty_text(option) for option in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, int))


def archive_time(value):
    if not isinstance(value, str):
        raise ValueError("缺少时间")
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("时间需包含时区")
    return timestamp


def verify_attachment(expected, actual, directory, unit_name, location, issues):
    source_id = expected.get("source_id")
    if (not nonempty_text(expected["name"]) or expected["name"] != actual["name"]
            or (source_id is not None and source_id != actual.get("source_id"))):
        issues.append(f"{location}：附件文件名或系统标识与网页不一致")

    raw_path = actual.get("path")
    if not raw_path or actual.get("download_status") not in CONFIRMED_DOWNLOADS:
        issues.append(f"{location}：原件下载未确认")
        return None
    try:
        original_link(directory, raw_path)
        original = (directory / raw_path).resolve()
        size = 0
        digest = hashlib.sha256()
        with original.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    except (ValueError, OSError, RuntimeError) as error:
        issues.append(f"{location}：{error}")
        return None
    captured_hash = actual.get("sha256")
    if not isinstance(captured_hash, str) or digest.hexdigest() != captured_hash.lower() or size == 0:
        issues.append(f"{location}：原件 SHA-256 缺失或与下载时不一致")
    if "size_bytes" in expected and (type(expected["size_bytes"]) is not int or expected["size_bytes"] != size):
        issues.append(f"{location}：原件字节数与系统明细不一致")
    if actual.get("original_opened") is not True:
        issues.append(f"{location}：未确认原件可以按实际格式打开")

    units = actual.get("content_units", [])
    if (not isinstance(units, list) or not units
            or any(not nonempty_text(unit) for unit in units)
            or len(set(units)) != len(units)):
        issues.append(f"{location}：缺少原件的页码、工作表或正文单元清单，或清单重复")
    parts = actual.get("text_parts", [])
    if (actual.get("text_status") != "全文已提取"
            or units != [part["location"] for part in parts]
            or any(not isinstance(part["text"], str)
                   or (not part["text"].strip() and part.get("blank") is not True)
                   for part in parts)):
        issues.append(f"{location}：全文识读未完成，或覆盖范围与原件不一致")
    if units != actual.get("seal_checked_locations") or not actual.get("seal_coverage"):
        issues.append(f"{location}：印章检查范围与原件不一致")
    seals = actual.get("seals", [])
    seal_status = actual.get("seal_status")
    if (seal_status not in {"未见印章", "有可辨识印章"}
            or bool(seals) != (seal_status == "有可辨识印章")
            or any(not seal.get("location") or compare_seal(seal, unit_name) == "无法判断"
                   for seal in seals)):
        issues.append(f"{location}：印章结果待复核或记录相互矛盾")
    return original


def verify(directory):
    record = load_json(directory / "record.json")
    source = load_json(directory / "source" / "portal-check.json")
    issues = []
    for key in IDENTITY:
        value = source.get(key)
        valid_identity = nonempty_text(value) or (key == "report_version" and value is None)
        if (key not in source or key not in record or source[key] != record[key]
                or not valid_identity):
            issues.append(f"{key}：单位身份或报送版本缺失，或与网页不一致")
    if source.get("entity_type") != EXPECTED_ENTITY or record.get("entity_type") != EXPECTED_ENTITY:
        issues.append(f"本技能仅核验「{EXPECTED_ENTITY}」归档")
    try:
        if archive_time(source.get("rechecked_at")) < archive_time(record.get("captured_at")):
            issues.append("网页复核时间早于本次采集时间")
    except ValueError:
        issues.append("采集时间或网页复核时间缺失，或未使用带时区的 ISO 8601 格式")
    for candidate, label in ((source, "网页复核记录"), (record, "采集记录")):
        entries = candidate.get("issues", [])
        if not isinstance(entries, list) or any(not nonempty_text(entry) for entry in entries):
            issues.append(f"{label}：issues 应为非空说明组成的数组，无缺项时可填空数组")
        else:
            issues.extend(f"{label}：{entry}" for entry in entries)

    for candidate, label in ((source, "网页复核记录"), (record, "采集记录")):
        tabs = candidate["sections"]
        if [tab["title"] for tab in tabs] != EXPECTED_TABS:
            issues.append(f"{label}：页签范围或顺序错误")
        for tab in tabs:
            if tab.get("status") != "已采集" or not tab["fields"]:
                issues.append(f"{label} / {tab['title']}：页签未完整采集")

    linked = set()
    for expected_tab, actual_tab in zip(source["sections"], record["sections"]):
        title = expected_tab["title"]
        expected_fields = expected_tab["fields"]
        actual_fields = actual_tab["fields"]
        if len(expected_fields) != len(actual_fields):
            issues.append(f"{title}：网页有 {len(expected_fields)} 项，归档有 {len(actual_fields)} 项")
        for index, (expected, actual) in enumerate(zip(expected_fields, actual_fields), 1):
            field_path = expected.get("path", [])
            location = f"{title} / 第 {index} 项"
            if (not nonempty_text(expected["label"]) or not isinstance(field_path, list)
                    or any(not nonempty_text(group) for group in field_path)):
                issues.append(f"{location}：网页复核记录的题目标题或层级无效")
                continue
            location += " / " + " / ".join([*field_path, expected["label"]])
            if (field_path != actual.get("path", []) or expected["label"] != actual["label"]
                    or not valid_value(expected["value"])
                    or json.dumps(expected["value"]) != json.dumps(actual["value"])):
                issues.append(f"{location}：题目位置、标题或填报值与网页不一致")
            expected_files = expected["attachments"]
            actual_files = actual.get("attachments", [])
            if len(expected_files) != len(actual_files):
                issues.append(f"{location}：网页有 {len(expected_files)} 份附件，归档有 {len(actual_files)} 份")
            for position, (before, after) in enumerate(zip(expected_files, actual_files), 1):
                file_location = f"{location} / 附件 {position} / {before['name']}"
                original = verify_attachment(before, after, directory, record["unit_name"],
                                             file_location, issues)
                if original is not None:
                    if original in linked:
                        issues.append(f"{file_location}：与其他附件登记共用同一原件路径")
                    linked.add(original)

    for file in sorted((directory / "attachments").rglob("*")):
        if file.is_file() and file.resolve() not in linked:
            issues.append(f"{file.relative_to(directory)}：附件原件没有与网页登记对应")

    try:
        expected_html = render_record(record, directory).replace("\r\n", "\n").replace("\r", "\n")
        if (directory / "index.html").read_text(encoding="utf-8-sig") != expected_html:
            issues.append("index.html 与当前采集记录重新生成的页面不一致")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        issues.append(f"无法核对 index.html：{error}")
    return issues


def write_report(directory, content):
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", suffix=".tmp",
                            prefix=".verification-", dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temporary.replace(directory / "verification.json")
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit_directory", type=Path)
    parser.add_argument("--write-report", action="store_true", help="also save verification.json")
    args = parser.parse_args()
    directory = args.unit_directory.resolve()
    try:
        issues = verify(directory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        issues = [f"缺少校验材料或格式无效：{error}"]
    report = {"status": "待复核" if issues else "校验通过",
              "verified_at": datetime.now(timezone.utc).isoformat(), "issues": issues}
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.write_report:
        try:
            write_report(directory, content)
        except OSError as error:
            report["status"] = "待复核"
            issues.append(f"无法写入 verification.json：{error}")
            content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(content, end="")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
