"""Collect visible evaluation details through an existing BrowserSkill session."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from build_archive import build_batch, complete_indicators, final_score, indicator_field, load, load_manifest, write_json


class Browser:
    def __init__(self, session):
        self.session = session
        self.context = None

    def request(self, *args, timeout=100):
        call = subprocess.run(["bsk", *args, "--session", self.session, "--json"],
                              capture_output=True, encoding="utf-8", timeout=timeout)
        try:
            reply = json.loads(call.stdout)
        except ValueError as error:
            detail = call.stderr.strip() or "未返回有效 JSON"
            raise RuntimeError(f"浏览器工具退出码 {call.returncode}：{detail}") from error
        if not isinstance(reply, dict) or call.returncode and reply.get("ok"):
            raise RuntimeError(f"浏览器工具返回异常，退出码 {call.returncode}")
        return reply

    def evaluate(self, expression, selector="form.ivu-form"):
        guard = json.dumps([{"target": selector, "field": "exists", "equals": True}])
        for _ in range(2):
            if self.context is None:
                reply = self.request("cooperate", "sync", "--settle")
                if not reply.get("context_id") and "frame is not responding" in reply.get("message", ""):
                    time.sleep(2)
                    reply = self.request("cooperate", "sync", "--settle")
                self.context = reply.get("context_id")
                if not self.context:
                    raise RuntimeError(reply.get("message", "浏览器控制同步失败"))
            reply = self.request("evaluate", expression, "--context", self.context,
                                 "--expect", guard, "--timeout", "2m", timeout=135)
            if reply.get("ok"):
                return reply["value"]
            data = reply.get("data", {})
            if data.get("phase") == "control" and data.get("effect_state") == "none":
                self.context = None
                continue
            if data.get("effect_state") == "unknown":
                raise RuntimeError("浏览器操作结果不明，需核对现场，避免重复下载")
            error = reply.get("error", {})
            raise RuntimeError(error.get("text") or reply.get("message") or "浏览器未完成读取")
        raise RuntimeError("浏览器控制上下文未恢复")

    def wait_for(self, selector, text=None, field="text"):
        fields = json.dumps([{"key": "value", "read": field}])
        deadline = time.monotonic() + 28
        while time.monotonic() < deadline:
            reply = self.request("read", "--selector", selector, "--fields-json", fields)
            values = [item["values"].get("value") for item in reply.get("items", [])]
            if any(isinstance(value, str) and (text is None or text in value) for value in values):
                return
            time.sleep(0.45)
        raise RuntimeError("等待页面数据超时，已保留本地采集进度")


def files_in(folder):
    result = {}
    for file in folder.iterdir():
        if file.is_file():
            info = file.stat()
            if info.st_size and file.suffix.lower() != ".crdownload":
                result[file] = (info.st_size, info.st_mtime_ns)
    return result


def download_name(path):
    # Chrome inserts a counter just before the original extension.
    return re.sub(r" \(\d+\)$", "", path.stem) + path.suffix


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def archive_download(item, destination, downloads, before, index):
    previous = None
    for _ in range(60):
        current = files_in(downloads)
        exact = []
        renamed = []
        for path, signature in current.items():
            if before.get(path) == signature:
                continue
            if path.name == item["name"]:
                exact.append(path)
            elif download_name(path) == item["name"]:
                renamed.append(path)
        candidates = exact + renamed
        if len(candidates) > 1:
            raise RuntimeError("发现多个同名下载，无法确认唯一原件")
        if len(candidates) == 1:
            source = candidates[0]
            match = (source, current[source])
            if previous == match and not any(downloads.glob("*.crdownload")):
                break
            previous = match
        else:
            previous = None
        time.sleep(0.5)
    else:
        raise RuntimeError("未确认本次单件下载，须核对浏览器下载记录")
    attachment_dir = destination / "attachments"
    attachment_dir.mkdir(exist_ok=True)
    clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", item["name"]).rstrip(" .")
    filename = Path(clean_name)
    checksum = digest(source)
    target = attachment_dir / f"{index:03d}-{filename.stem[:95]}-{checksum[:12]}{filename.suffix}"
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        shutil.copyfile(source, temporary)
        if digest(temporary) != checksum:
            raise RuntimeError("附件复制后哈希不一致")
        temporary.replace(target)
    if digest(target) != checksum:
        raise RuntimeError("本地已有附件与本次下载哈希不一致")
    item.update(path=target.relative_to(destination).as_posix(), sha256=checksum,
                size=target.stat().st_size, status="原件已归档，格式与全文待识读")


def reusable_file(folder, item):
    path = item.get("path")
    if not path or not item.get("sha256"):
        return False
    original = (folder / path).resolve()
    return (original.is_relative_to((folder / "attachments").resolve()) and original.is_file()
            and original.stat().st_size > 0 and digest(original) == item["sha256"].lower())


def complete_project(item, folder):
    if not item["fields"] or final_score(item) == "—":
        return False
    for field in map(indicator_field, item["fields"]):
        kind = field.get("kind")
        if kind == "attachment":
            if field["list_confirmed"] is not True or any(
                    not reusable_file(folder, attachment) for attachment in field["attachments"]):
                return False
        elif kind == "applicability":
            if not field["applicability"]:
                return False
        elif kind == "unclassified" or "answers" in field and not field["answers"]:
            return False
    return True


def run(batch, session, downloads, limit=None, verify=False, unit=None):
    manifest = load_manifest(batch)
    browser = Browser(session)
    script = Path(__file__).with_name("evaluation_detail.js").read_text(encoding="utf-8")
    rows = [row for row in manifest["rows"] if row["eligible"] and row["has_detail"]
            and (unit is None or row["code"] == unit)]
    if unit is not None and not rows:
        raise ValueError("指定单位不在本次可采集名录内")
    attempted = 0
    for row in rows:
        code = row["code"]
        if not code.isalnum():
            raise ValueError("单位代码不适合作为本地目录名")
        folder = batch / code
        output = folder / "record.json"
        old = load(output) if output.exists() else {}
        same_version = bool(old and old.get("unit_code") == code and old.get("unit_name") == row["name"]
                            and row["report_version"] and old.get("report_version") == row["report_version"])
        structure_ready = (same_version and old.get("basic") and complete_indicators(old)
                           and (old.get("supplementary") or {}).get("confirmed") is True)
        if verify and not structure_ready:
            print(f"{code}：请先采齐同一上报版本的三部分，再独立复读", flush=True)
            continue
        if not verify and structure_ready and all(complete_project(item, folder) for item in old["items"]):
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        folder.mkdir(exist_ok=True)
        target = folder / "source" / "portal-check.json" if verify else output
        target.parent.mkdir(exist_ok=True)
        progress = target.with_name("latest-attempt.json")
        previous_attempt = load(progress) if not verify and progress.exists() else {}
        if (previous_attempt and (
                previous_attempt.get("unit_code") != code
                or previous_attempt.get("unit_name") != row["name"]
                or not row["report_version"]
                or previous_attempt.get("report_version") != row["report_version"])):
            previous_attempt = {}
        attempt_file = target.with_name("portal-attempt.json")
        started = datetime.now(timezone.utc).isoformat()
        if verify:
            write_json(attempt_file, {"started_at": started, "status": "started"})

        def stage(name, selector=".content_top", **options):
            args = json.dumps({"row": row, "task": manifest["task"], "stage": name, **options})
            return browser.evaluate(f"({script})({args})", selector)

        record = None
        opened = False
        uncertain = False

        def checkpoint():
            write_json(progress, record)
            if not verify and (not same_version or not old or
                               len(record["items"]) > len(old.get("items", [])) or
                               (record.get("supplementary") or {}).get("confirmed")):
                write_json(output, record)

        try:
            result = stage("open", "form.ivu-form")
            if result["issues"]:
                raise ValueError(result["issues"][0])
            opened = True
            browser.wait_for(".content_top", row["name"])
            browser.wait_for(".ivu-collapse-item table input", row["name"], "value")
            record = stage("basic")
            record["captured_at"] = started
            if record["issues"] or not record["basic"]:
                raise ValueError("基本信息未确认：" + "；".join(record["issues"]))
            scores = stage("scores")
            if scores["issues"]:
                raise ValueError(scores["issues"][0])
            browser.wait_for(".titleSection", "评价指标打分")
            browser.wait_for(".tiWrap .pc-container.showTopic")
            file_offset = 0
            offset = 0
            while True:
                part = stage("items", offset=offset)
                if not part["items"]:
                    raise ValueError("未读到评价项目：" + "；".join(part["issues"]))
                if offset == 0:
                    for key in ("expected_items", "score_summary", "indicator_plan"):
                        record[key] = part[key]
                if part["indicator_plan"] != record["indicator_plan"]:
                    raise ValueError("同一单位的系统指标目录发生变化")
                item = part["items"][0]
                record["items"].append(item)
                record["issues"].extend(part["issues"])
                prior_fields = []
                for prior in (old if same_version and not verify else {}, previous_attempt):
                    prior_items = prior.get("items", [])
                    if prior.get("indicator_plan") == part["indicator_plan"] and offset < len(prior_items):
                        prior_item = prior_items[offset]
                        if prior_item.get("title") == item["title"]:
                            prior_fields.append(prior_item["fields"])
                upload_index = -1
                for field_index, field in enumerate(item["fields"]):
                    if field.get("kind") != "attachment":
                        continue
                    upload_index += 1
                    matching = []
                    for fields in prior_fields:
                        if field_index >= len(fields):
                            continue
                        previous = fields[field_index]
                        old_files = previous.get("attachments", [])
                        if (field["list_confirmed"] and previous.get("list_confirmed") is True
                                and [a["name"] for a in old_files] == [a["name"] for a in field["attachments"]]
                                and all(fields[i].get("label") == item["fields"][i].get("label")
                                        for i in range(field_index + 1))):
                            matching.append(old_files)
                    for index, entry in enumerate(field["attachments"]):
                        file_offset += 1
                        if verify:
                            continue
                        candidates = [files[index] for files in matching if reusable_file(folder, files[index])]
                        reuse = next((attachment for attachment in candidates
                                      if entry["metadata"] and attachment.get("metadata") == entry["metadata"]), None)
                        if reuse:
                            field["attachments"][index] = {**reuse, **entry}
                            continue
                        before = files_in(downloads)
                        requested = stage("items", offset=offset, file={"field": upload_index, "index": index, "entry": entry})
                        if not requested.get("download_requested"):
                            raise RuntimeError("未确认单件下载操作：" + "；".join(requested["issues"]))
                        archive_download(entry, folder, downloads, before, file_offset)
                        reuse = next((attachment for attachment in candidates
                                      if attachment["sha256"].lower() == entry["sha256"]), None)
                        if reuse:
                            field["attachments"][index] = {**entry, **reuse, "metadata": entry["metadata"],
                                                           "page": entry["page"], "size": entry["size"]}
                        checkpoint()
                checkpoint()
                offset += 1
                if offset >= record["expected_items"]:
                    break
            if not complete_indicators(record):
                raise ValueError("评价项目与系统目录不一致")
            extra = stage("supplementary")
            record["supplementary"] = extra.get("supplementary")
            record["issues"].extend(extra["issues"])
            if not (record["supplementary"] or {}).get("confirmed"):
                raise ValueError("补充说明未确认采集")
            if verify and (record["issues"] or any(
                    field.get("kind") == "attachment" and field.get("list_confirmed") is not True
                    for item in record["items"] for field in item["fields"])):
                raise ValueError("独立网页复核存在缺项")
            checkpoint()
            if verify:
                write_json(target, record)
                write_json(attempt_file, {"started_at": started, "status": "completed"})
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
            uncertain = True
            print(f"{code}：浏览器或下载状态待核实。{error}", flush=True)
            if record is not None:
                record["issues"].append(str(error))
                checkpoint()
        except ValueError as error:
            print(f"{code}：本单位采集待复核。{error}", flush=True)
            if record is not None:
                record["issues"].append(str(error))
                checkpoint()
        finally:
            if opened and not uncertain:
                try:
                    closed = stage("close", "body")
                    uncertain = bool(closed["issues"])
                except (RuntimeError, subprocess.TimeoutExpired) as error:
                    print(f"{code}：关闭明细失败。{error}", flush=True)
                    uncertain = True
        if uncertain:
            break
    print(datetime.now(timezone.utc).isoformat(), build_batch(batch), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--unit", help="only process the listed unit code")
    args = parser.parse_args()
    if not args.verify and args.downloads is None:
        parser.error("下载时需要 --downloads")
    if args.downloads is not None and not args.downloads.is_dir():
        parser.error("--downloads 必须是浏览器实际使用且已存在的目录")
    run(args.batch.resolve(), args.session, args.downloads, args.limit, args.verify, args.unit)
