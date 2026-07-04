import json
import time
from datetime import datetime
from pathlib import Path

import requests


UPLOAD_LOG = Path("tpa_upload_results.log")
PENDING_FILE = Path("tpa_upload_pending.json")
DEFAULT_UPLOAD_URL = "http://norskytech.com:8888/tpa/uploadOrder"
SUCCESS_CODES = {1}


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_op_time_ms(*values):
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        if text.isdigit():
            number = int(text)
            return number * 1000 if number < 10_000_000_000 else number
        normalized = text.split(" - ", 1)[0].replace("Z", "").split(".", 1)[0].strip()
        normalized = normalized.replace("T", " ")
        parts = normalized.split()
        if len(parts) >= 3 and parts[-1].upper() in ("AM", "PM"):
            date_part, time_part, meridiem = parts[0], parts[1], parts[-1].upper()
            hour_text = time_part.split(":", 1)[0]
            if hour_text.isdigit() and (int(hour_text) == 0 or int(hour_text) > 12):
                normalized = f"{date_part} {time_part}"
            else:
                normalized = f"{date_part} {time_part} {meridiem}"
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %I:%M:%S %p",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y %I:%M %p",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%m/%d/%Y",
        ):
            try:
                return int(datetime.strptime(normalized, fmt).timestamp() * 1000)
            except ValueError:
                pass
    return int(datetime.now().timestamp() * 1000)


def append_upload_log(message):
    line = f"[{now_text()}] {message}"
    print(line, flush=True)
    with UPLOAD_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_pending_orders():
    if not PENDING_FILE.exists():
        return []
    try:
        data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_pending_orders(rows):
    PENDING_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_order_key(order):
    return "|".join(str(order.get(key) or "") for key in ("systemName", "orderNo", "status", "opTime"))


def merge_orders(old_rows, new_rows):
    merged = {}
    for row in old_rows + new_rows:
        if row.get("orderNo") and row.get("status") is not None:
            merged[normalize_order_key(row)] = row
    return list(merged.values())


def post_one_order(api_url, order):
    response = requests.post(api_url, json=order, timeout=30)
    text = response.text
    try:
        data = response.json()
    except ValueError:
        data = {"code": None, "msg": text[:500]}
    return response.status_code, data, text


def upload_orders(api_url, orders, interval_seconds=0.5):
    if not api_url:
        append_upload_log("未配置上传接口地址，本轮变化已保存为待上传。")
        pending = merge_orders(load_pending_orders(), orders)
        save_pending_orders(pending)
        return {"sent": 0, "success": 0, "failed": len(orders), "pending": len(pending), "results": []}

    queue = merge_orders(load_pending_orders(), orders)
    save_pending_orders(queue)
    if not queue:
        append_upload_log("没有需要上传的订单变化。")
        return {"sent": 0, "success": 0, "failed": 0, "pending": 0, "results": []}

    append_upload_log(f"开始上传订单变化：{len(queue)} 条，接口：{api_url}")
    success_keys = set()
    results = []
    for index, order in enumerate(queue, start=1):
        try:
            status_code, data, raw_text = post_one_order(api_url, order)
            ok = data.get("code") in SUCCESS_CODES
            result = {
                "order": order,
                "http_status": status_code,
                "response": data,
                "success": ok,
            }
            results.append(result)
            if ok:
                success_keys.add(normalize_order_key(order))
                append_upload_log(f"上传成功 {index}/{len(queue)}：{order}，返回：{data}")
            else:
                append_upload_log(f"上传失败 {index}/{len(queue)}：{order}，返回：{data}")
        except Exception as exc:
            results.append({"order": order, "success": False, "error": str(exc)})
            append_upload_log(f"上传异常 {index}/{len(queue)}：{order}，错误：{exc}")
        time.sleep(interval_seconds)

    pending = [row for row in queue if normalize_order_key(row) not in success_keys]
    save_pending_orders(pending)
    append_upload_log(f"上传完成：成功 {len(success_keys)} 条，待重传 {len(pending)} 条。")
    return {
        "sent": len(queue),
        "success": len(success_keys),
        "failed": len(pending),
        "pending": len(pending),
        "results": results,
    }
