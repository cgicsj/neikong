"""Collect visible evaluation details through an existing BrowserSkill session."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from build_archive import build_batch, complete_indicators, load, write_json


class Browser:
    def __init__(self, session):
        self.session = session
        self.context = None

    def request(self, *args, timeout=100):
        call = subprocess.run(["bsk", *args, "--session", self.session, "--json"],
                              capture_output=True, encoding="utf-8", timeout=timeout)
        if not call.stdout:
            raise RuntimeError("浏览器工具没有返回数据")
        return json.loads(call.stdout)

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


def archive_downloads(record, destination, downloads, before, start=0):
    items = [item for section in record["items"] for field in section["fields"] for item in field.get("attachments", [])]
    if not items:
        return
    requested = defaultdict(list)
    for index, item in enumerate(items, start + 1):
        item["status"] = "未下载"
        if item.get("download_requested"):
            requested[item["name"]].append((index, item))
    if not requested:
        return
    captures = {}
    for _ in range(12):
        time.sleep(0.55)
        current = files_in(downloads)
        captures = defaultdict(list)
        for path, signature in current.items():
            if before.get(path) != signature:
                key = path.name if path.name in requested else download_name(path)
                if key in requested:
                    captures[key].append(path)
        if all(len(captures[name]) >= len(entries) for name, entries in requested.items()):
            break
    attachment_dir = destination / "attachments"
    attachment_dir.mkdir(exist_ok=True)
    for name, entries in requested.items():
        paths = captures[name]
        if len(paths) != len(entries):
            for _, item in entries:
                item["status"] = "浏览器未确认唯一原件，须回到原题逐件下载"
            continue
        if len(paths) > 1:
            hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            if len(hashes) != 1:
                for _, item in entries:
                    item["status"] = "同名原件内容不同，须回到原题分别下载"
                continue
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
        suffix = Path(clean_name).suffix
        stem = Path(clean_name).stem[:110]
        for (index, item), source in zip(entries, sorted(paths)):
            new_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            target = attachment_dir / f"{index:03d}-{stem}{suffix}"
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != new_hash:
                target = attachment_dir / f"{index:03d}-{stem}-{new_hash[:12]}{suffix}"
            if not target.exists():
                shutil.copyfile(source, target)
            item.update(path=target.relative_to(destination).as_posix(),
                        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                        status="原件已归档，格式与全文待识读")


def run(batch, session, downloads, limit=None, verify=False, unit=None):
    manifest = load(batch / "source" / "名录.json")
    browser = Browser(session)
    script = Path(__file__).with_name("evaluation_detail.js").read_text(encoding="utf-8")
    collected = 0
    if unit is not None and not any(row["code"] == unit and row["eligible"] and row["has_detail"]
                                    for row in manifest["rows"]):
        raise ValueError("指定单位不在本次可采集名录内")
    for row in manifest["rows"]:
        if not row["eligible"] or not row["has_detail"]:
            continue
        code = row["code"]
        if unit is not None and code != unit:
            continue
        if not code.isalnum():
            raise ValueError("单位代码不适合作为本地目录名")
        folder = batch / code
        output = folder / "record.json"
        old = load(output) if output.exists() else {}
        complete = complete_indicators(old)
        if (verify and not complete) or (not verify and complete):
            continue
        folder.mkdir(exist_ok=True)
        target = folder / "source" / "portal-check.json" if verify else output
        if verify:
            target.parent.mkdir(exist_ok=True)
        progress = target.with_name("latest-attempt.json")
        record = None
        file_offset = 0
        try:
            def stage(name, selector):
                args = json.dumps({"row": row, "task": manifest["task"], "stage": name})
                return browser.evaluate(f"({script})({args})", selector)

            record = stage("open", "form.ivu-form")
            if not record["issues"]:
                browser.wait_for(".content_top", row["name"])
                browser.wait_for(".ivu-collapse-item table input", row["name"], "value")
                record = stage("basic", ".content_top")
            if not target.exists() or not load(target)["items"]:
                write_json(target, record)
            if record["basic"]:
                scores = stage("scores", ".content_top")
                record["issues"].extend(scores["issues"])
                if scores["issues"]:
                    raise RuntimeError(scores["issues"][0])
                browser.wait_for(".titleSection", "评价指标打分")
                browser.wait_for(".tiWrap .pc-container.showTopic")
            while record["basic"]:
                before = files_in(downloads) if not verify else {}
                items = record["items"] if record else []
                args = json.dumps({"row": row, "download": not verify, "offset": len(items)})
                part = browser.evaluate(f"({script})({args})", ".content_top")
                if not items:
                    for key in ("expected_items", "score_summary", "indicator_plan"):
                        if key in part:
                            record[key] = part[key]
                if part.get("indicator_plan") != record.get("indicator_plan"):
                    raise RuntimeError("同一单位的系统指标目录发生变化")
                if not verify:
                    archive_downloads(part, folder, downloads, before, file_offset)
                piece = part["items"]
                file_offset += sum(len(field.get("attachments", [])) for item in piece for field in item["fields"])
                record["items"].extend(piece)
                record["issues"].extend(part["issues"])
                write_json(progress, record)
                if not target.exists() or len(record["items"]) >= len(load(target)["items"]):
                    write_json(target, record)
                if not piece or len(record["items"]) >= record.get("expected_items", 0):
                    break
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            if record is not None:
                record["issues"].append(str(error))
                write_json(progress, record)
                if not target.exists() or len(record["items"]) >= len(load(target)["items"]):
                    write_json(target, record)
            print(f"{code}：本次停止，浏览器待核实。{error}", flush=True)
            break
        files = [item for section in record["items"] for field in section["fields"]
                 for item in field.get("attachments", [])]
        collected += 1
        print(f"{code}：{len(record['items'])}/{record.get('expected_items', '?')} 项，"
              f"附件 {len(files) if verify else sum(bool(item.get('path')) for item in files)}/{len(files)}，"
              f"异常 {len(record['issues'])}", flush=True)
        if not record["items"] and len(record["issues"]):
            print(record["issues"][0], flush=True)
        build_batch(batch)
        if limit is not None and collected >= limit:
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
    run(args.batch.resolve(), args.session, args.downloads, args.limit, args.verify, args.unit)
