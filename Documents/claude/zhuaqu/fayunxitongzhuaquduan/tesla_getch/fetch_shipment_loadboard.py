import csv
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_to_api import post_orders, tesla_orders
from tpa_order_uploader import DEFAULT_UPLOAD_URL, parse_op_time_ms, upload_orders


BROWSER_STORAGE_FILE = Path("tesla_supplier_browser_storage.json")
NETWORK_FULL_FILE = Path("tesla_network_sensitive_full.json")
OUTPUT_JSON = Path("shipment_loadboard.json")
OUTPUT_CSV = Path("shipment_loadboard.csv")
OUTPUT_SELECTED_CSV = Path("shipment_loadboard_selected.csv")
OUTPUT_SELECTED_ALL_CSV = Path("shipment_loadboard_selected_all.csv")
OUTPUT_PENDING_CHANGES_JSON = Path("tesla_pending_changes.json")
HISTORY_DB = Path("tesla_loadboard_history.db")
DEFAULT_LOADBOARD_ENDPOINT = os.getenv("LOADBOARD_ENDPOINT", "ROShipmentLoadBoard")
DEFAULT_API_BASE = os.getenv(
    "TESLA_SHIPMENT_API_BASE",
    "https://akamai-apigateway-shipmentplanningapi.tesla.com/ShipmentPlanningAPI",
)
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
TARGET_SHIP_DATE = os.getenv("TARGET_SHIP_DATE")
TARGET_DAYS = int(os.getenv("TARGET_DAYS", "3"))
SELECTED_COLUMNS = [
    "装箱单",
    "发运编号",
    "发运日期",
    "状态编号",
    "发运状态",
    "抓取时间",
    "收货时间",
    "取消时间",
    "上传状态码",
    "上传时间戳",
    "上传时间",
    "上传返回",
]
SHIPMENT_STATUS_TEXT = {
    1: "Pending Approval",
    2: "Pending Approval",
    3: "ASN Pending",
    4: "ASN Submitted",
    5: "Cancelled",
    8: "NEW",
}
TESLA_UPLOAD_STATUS = {
    8: 1,
    3: 1,
    4: 2,
    5: 3,
}
TRANSMIT_STATUS_CODES = set(TESLA_UPLOAD_STATUS)
STATUS_ALIASES = {
    "PENDING APPROVAL": "Pending Approval",
    "ASN PENDING": "ASN Pending",
    "CANCELLED": "Cancelled",
    "CANCELED": "Cancelled",
    "ASN SUBMITTED": "ASN Submitted",
    "NEW": "NEW",
}


def load_json(path):
    if not path.exists():
        raise RuntimeError(f"Missing {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


def supplier_local_storage():
    for item in load_json(BROWSER_STORAGE_FILE):
        if item.get("origin") == "https://suppliers.teslamotors.com":
            return item.get("localStorage", {})
    raise RuntimeError("Could not find suppliers.teslamotors.com localStorage.")


def valid_local_storage(local_storage):
    return bool(auth_token_from_storage(local_storage))


def first_successful_loadboard_request():
    if not NETWORK_FULL_FILE.exists():
        return {}
    for item in load_json(NETWORK_FULL_FILE):
        if (
            item.get("method") == "GET"
            and item.get("status") == 200
            and "ShipmentLoadboard?" in item.get("url", "")
        ):
            return item
    return {}


def build_headers(captured_request, local_storage):
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "referer": "https://suppliers.teslamotors.com/",
        "user-agent": "Mozilla/5.0",
    }

    token = auth_token_from_storage(local_storage)
    csrf = clean_storage_value(local_storage.get("shipmentplanning:attrs:csrfToken") or local_storage.get("ssCSRFToken"))
    email = clean_storage_value(local_storage.get("ssEmail"))
    custom_headers = local_storage.get("shipmentplanning:attrs:customHeaders")

    if custom_headers:
        try:
            headers.update({k.lower(): v for k, v in json.loads(custom_headers).items()})
        except json.JSONDecodeError:
            pass
    if token:
        headers["authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    if csrf:
        headers["x-requestverificationtoken"] = csrf
    if email:
        headers["x-portalidentity-username"] = email
    data_region = clean_storage_value(local_storage.get("DataRegion"))
    if data_region:
        headers["x-data-region"] = data_region

    captured_headers = captured_request.get("request_headers") or {}
    for key in ("authorization", "x-requestverificationtoken", "x-portalidentity-username", "x-data-region"):
        if key not in headers and captured_headers.get(key):
            headers[key] = captured_headers[key]

    return headers


def default_params(local_storage, top=100, endpoint=DEFAULT_LOADBOARD_ENDPOINT):
    supplier_code = clean_storage_value(
        local_storage.get("ssUserSupplierCode") or local_storage.get("shipmentplanning:attrs:supplierCode")
    )
    if not supplier_code:
        supplier_code = "209051"

    params = {
        "skip": 0,
        "top": top,
        "count": "true",
        "supplierCode": supplier_code,
        "isFilterSearch": "false" if endpoint == "ROShipmentLoadBoard" else "true",
        "shipmentNum": "",
        "trackingNum": "",
        "packingSlipNumber": "",
        "shipDate": "",
        "shipmentStatusId": "",
        "pickupLocationId": "",
        "destinationLocationId": "",
        "startDate": "",
        "endDate": "",
        "licensePlateNum": "",
        "dateASC": 1,
        "shipmentStatusASC": 1,
        "isAsnPendingCountQuery": "true" if endpoint == "ROShipmentLoadBoard" else "false",
        "isEnableElasticSearch": "true",
        "itinernarySourceTypeId": "20" if endpoint == "ROShipmentLoadBoard" else "1,2,3,10,21",
        "poNumber": "",
        "partNumber": "",
        "licensePlatePurposes": "",
    }
    return params


def clean_storage_value(value):
    if value is None:
        return value
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return parsed if isinstance(parsed, str) else value


def api_base_from_storage(local_storage):
    raw_value = clean_storage_value(local_storage.get("ShipmentPlanningApiUrl"))
    if isinstance(raw_value, str) and raw_value.startswith("http"):
        return raw_value.rstrip("/")
    return DEFAULT_API_BASE.rstrip("/")


def auth_token_from_storage(local_storage):
    shipment_token = local_storage.get("shipmentplanning:token")
    if shipment_token:
        try:
            parsed = json.loads(shipment_token)
            if isinstance(parsed, dict):
                for key in ("accessToken", "access_token", "token"):
                    if parsed.get(key):
                        return parsed[key]
        except json.JSONDecodeError:
            pass

    return clean_storage_value(local_storage.get("access_token"))


def flatten_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("data", "Data", "items", "Items", "result", "Result", "value", "Value"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = flatten_records(value)
            if nested:
                return nested
    return []


def write_csv(records):
    if not records:
        return
    keys = sorted({key for row in records if isinstance(row, dict) for key in row.keys()})
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in records:
            writer.writerow({key: row.get(key) for key in keys})


def record_key(row):
    for key in ("ShipmentId", "ShipmentNumber", "PackingSlipNumber", "TrackingNumber"):
        value = row.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def dedupe_records(records):
    deduped = {}
    for row in records:
        if isinstance(row, dict):
            deduped[record_key(row)] = row
    return list(deduped.values())


def clean_html_breaks(value):
    if value is None:
        return ""
    return str(value).replace("<br/>", " ").replace("<br>", " ").strip()


def combined_status(row):
    status_code = shipment_status_code(row)
    if status_code in SHIPMENT_STATUS_TEXT:
        return SHIPMENT_STATUS_TEXT[status_code]

    for key in ("ShipmentStatusName", "ShipmentStatus", "StatusName", "Status", "发运状态"):
        value = row.get(key)
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            continue
        normalized = normalize_status(value)
        if normalized:
            return normalized

    if row.get("ShipmentStatusId") not in (None, ""):
        return f"UNKNOWN({row.get('ShipmentStatusId')})"
    return ""


def shipment_status_code(row):
    value = row.get("ShipmentStatusId") or row.get("状态编号")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def should_transmit_status(row):
    return shipment_status_code(row) in TRANSMIT_STATUS_CODES


def normalize_status(value):
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return STATUS_ALIASES.get(text.upper(), text)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def delivery_time(row, status):
    if status != "ASN Submitted":
        return ""
    return row.get("DeliveryDateLocal") or row.get("DeliveryDate") or ""


def cancelled_time(row, status):
    if status != "Cancelled":
        return ""
    return row.get("CancelDateLocal") or row.get("CancelledDateLocal") or row.get("CancelDate") or now_text()


def selected_row(row, fetch_time=None, existing=None):
    status = combined_status(row)
    existing = existing or {}
    fetch_time = fetch_time or now_text()
    return {
        "装箱单": row.get("PackingSlipNumber") or "",
        "发运编号": row.get("ShipmentNumber") or "",
        "发运日期": row.get("ShipDateLocal") or row.get("ShipDate") or "",
        "状态编号": shipment_status_code(row) or "",
        "发运状态": status,
        "抓取时间": existing.get("抓取时间") or fetch_time,
        "收货时间": existing.get("收货时间") or delivery_time(row, status),
        "取消时间": existing.get("取消时间") or cancelled_time(row, status),
        "上传状态码": existing.get("上传状态码", ""),
        "上传时间戳": existing.get("上传时间戳", ""),
        "上传时间": existing.get("上传时间", ""),
        "上传返回": existing.get("上传返回", ""),
    }


def ensure_history_db():
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tesla_shipments (
                shipment_no TEXT PRIMARY KEY,
                packing_no TEXT,
                ship_date TEXT,
                status TEXT,
                status_code INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                received_at TEXT,
                cancelled_at TEXT,
                uploaded_order_status INTEGER,
                uploaded_op_time INTEGER,
                uploaded_at TEXT,
                upload_response TEXT,
                raw_json TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(tesla_shipments)").fetchall()
        }
        if "status_code" not in columns:
            conn.execute("ALTER TABLE tesla_shipments ADD COLUMN status_code INTEGER")
        if "uploaded_order_status" not in columns:
            conn.execute("ALTER TABLE tesla_shipments ADD COLUMN uploaded_order_status INTEGER")
        if "uploaded_op_time" not in columns:
            conn.execute("ALTER TABLE tesla_shipments ADD COLUMN uploaded_op_time INTEGER")
        if "uploaded_at" not in columns:
            conn.execute("ALTER TABLE tesla_shipments ADD COLUMN uploaded_at TEXT")
        if "upload_response" not in columns:
            conn.execute("ALTER TABLE tesla_shipments ADD COLUMN upload_response TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tesla_status_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_no TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                changed_at TEXT NOT NULL
            )
            """
        )


def is_today_ship_date(row):
    ship_date = parse_ship_date(record_ship_date(row))
    return ship_date == datetime.now().date()


def update_history(records):
    ensure_history_db()
    now = now_text()
    changed_records = []
    with sqlite3.connect(HISTORY_DB) as conn:
        for row in records:
            selected = selected_row(row, fetch_time=now)
            shipment_no = selected.get("发运编号") or selected.get("装箱单")
            if not shipment_no:
                continue
            status = selected.get("发运状态") or "NEW"
            status_code = selected.get("状态编号") or None
            existing = conn.execute(
                """
                SELECT status, first_seen_at, received_at, cancelled_at, status_code, uploaded_order_status, uploaded_op_time
                FROM tesla_shipments WHERE shipment_no = ?
                """,
                (shipment_no,),
            ).fetchone()
            is_new = existing is None
            old_status_code = existing[4] if existing else None
            uploaded_order_status = existing[5] if existing else None
            uploaded_op_time = existing[6] if existing else None
            status_changed = existing is not None and old_status_code != status_code
            received_at = (existing[2] if existing else "") or selected.get("收货时间") or (now if status == "ASN Submitted" else "")
            cancelled_at = (existing[3] if existing else "") or selected.get("取消时间") or (now if status == "Cancelled" else "")
            first_seen_at = existing[1] if existing else now

            conn.execute(
                """
                INSERT INTO tesla_shipments (
                    shipment_no, packing_no, ship_date, status, first_seen_at,
                    last_seen_at, received_at, cancelled_at, raw_json, status_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shipment_no) DO UPDATE SET
                    packing_no = excluded.packing_no,
                    ship_date = excluded.ship_date,
                    status = excluded.status,
                    status_code = excluded.status_code,
                    last_seen_at = excluded.last_seen_at,
                    received_at = COALESCE(NULLIF(tesla_shipments.received_at, ''), excluded.received_at),
                    cancelled_at = COALESCE(NULLIF(tesla_shipments.cancelled_at, ''), excluded.cancelled_at),
                    raw_json = excluded.raw_json
                """,
                (
                    shipment_no,
                    selected.get("装箱单") or "",
                    selected.get("发运日期") or "",
                    status,
                    first_seen_at,
                    now,
                    received_at,
                    cancelled_at,
                    json.dumps(row, ensure_ascii=False),
                    status_code,
                ),
            )

            if status_changed:
                conn.execute(
                    """
                    INSERT INTO tesla_status_events (shipment_no, old_status, new_status, changed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (shipment_no, str(old_status_code), str(status_code), now),
                )

            upload_order = tpa_upload_order(row)
            if upload_order and (
                is_new
                or status_changed
                or uploaded_order_status != upload_order["status"]
                or uploaded_op_time != upload_order["opTime"]
            ):
                changed = dict(row)
                changed["状态编号"] = status_code
                changed["发运状态"] = status
                changed["抓取时间"] = first_seen_at
                changed["收货时间"] = received_at
                changed["取消时间"] = cancelled_at
                changed_records.append(changed)

    return changed_records


def mark_uploaded_orders(upload_result):
    if not upload_result:
        return 0
    success_items = [item for item in upload_result.get("results", []) if item.get("success")]
    if not success_items:
        return 0
    ensure_history_db()
    uploaded_at = now_text()
    updated = 0
    with sqlite3.connect(HISTORY_DB) as conn:
        for item in success_items:
            order = item.get("order") or {}
            order_no = order.get("orderNo")
            upload_status = order.get("status")
            upload_op_time = order.get("opTime")
            if not order_no or upload_status is None or upload_op_time is None or order.get("systemName") != "TPA12":
                continue
            cursor = conn.execute(
                """
                UPDATE tesla_shipments
                SET uploaded_order_status = ?, uploaded_op_time = ?, uploaded_at = ?, upload_response = ?
                WHERE (packing_no = ? OR shipment_no = ?)
                """,
                (
                    upload_status,
                    upload_op_time,
                    uploaded_at,
                    json.dumps(item.get("response") or item.get("error") or "", ensure_ascii=False),
                    order_no,
                    order_no,
                ),
            )
            updated += cursor.rowcount
    mark_selected_all_csv_uploaded(success_items)
    return updated


def mark_selected_all_csv_uploaded(success_items):
    if not OUTPUT_SELECTED_ALL_CSV.exists():
        return 0
    rows = read_existing_selected_rows()
    if not rows:
        return 0
    uploaded_at = now_text()
    updated = 0
    for item in success_items:
        order = item.get("order") or {}
        if order.get("systemName") != "TPA12":
            continue
        order_no = order.get("orderNo")
        if not order_no:
            continue
        for row in rows:
            if order_no not in (row.get("装箱单"), row.get("发运编号")):
                continue
            row["上传状态码"] = str(order.get("status"))
            row["上传时间戳"] = str(order.get("opTime"))
            row["上传时间"] = uploaded_at
            row["上传返回"] = json.dumps(item.get("response") or item.get("error") or "", ensure_ascii=False)
            updated += 1
    if updated:
        with OUTPUT_SELECTED_ALL_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SELECTED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    return updated


def pending_change_row(row):
    selected = selected_row(row)
    return {
        "customer_type": "TESLA",
        "packing_no": selected.get("装箱单", ""),
        "shipment_no": selected.get("发运编号", ""),
        "status_code": selected.get("状态编号", ""),
        "status_text": selected.get("发运状态", ""),
        "fetched_at": selected.get("抓取时间", ""),
        "received_at": selected.get("收货时间", ""),
        "cancelled_at": selected.get("取消时间", ""),
    }


def write_pending_changes_json(records):
    payload = {
        "generated_at": now_text(),
        "records": [pending_change_row(row) for row in records],
    }
    OUTPUT_PENDING_CHANGES_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def tpa_upload_order(row):
    status_code = shipment_status_code(row)
    upload_status = TESLA_UPLOAD_STATUS.get(status_code)
    if upload_status is None:
        return None
    selected = selected_row(row)
    return {
        "orderNo": selected.get("装箱单") or selected.get("发运编号"),
        "systemName": "TPA12",
        "opTime": parse_op_time_ms(selected.get("收货时间"), selected.get("发运日期"), selected.get("抓取时间")),
        "status": upload_status,
    }


def tpa_upload_orders(rows):
    return [order for order in (tpa_upload_order(row) for row in rows) if order]


def write_selected_csv(records):
    fetch_time = now_text()
    with OUTPUT_SELECTED_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SELECTED_COLUMNS)
        writer.writeheader()
        for row in records:
            writer.writerow(selected_row(row, fetch_time=fetch_time))


def selected_key(row):
    return row.get("发运编号") or row.get("发货编号") or row.get("装箱单") or json.dumps(row, ensure_ascii=False, sort_keys=True)


def read_existing_selected_rows():
    if not OUTPUT_SELECTED_ALL_CSV.exists():
        return []
    with OUTPUT_SELECTED_ALL_CSV.open(newline="", encoding="utf-8-sig") as f:
        return [
            row
            for row in csv.DictReader(f)
            if should_keep_ship_date(str(row.get("发运日期", "")).split(" ", 1)[0])
        ]


def write_selected_all_csv(records):
    merged = {}
    for row in read_existing_selected_rows():
        if "发运编号" not in row and row.get("发货编号"):
            row["发运编号"] = row.get("发货编号", "")
        if "发运状态" not in row and row.get("发货状态"):
            row["发运状态"] = normalize_status(row.get("发货状态"))
        merged[selected_key(row)] = row
    fetch_time = now_text()
    for raw_row in records:
        base_row = selected_row(raw_row)
        row = selected_row(raw_row, fetch_time=fetch_time, existing=merged.get(selected_key(base_row)))
        merged[selected_key(row)] = row

    with OUTPUT_SELECTED_ALL_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SELECTED_COLUMNS)
        writer.writeheader()
        writer.writerows(merged.values())
    return len(merged)


def record_ship_date(row):
    value = row.get("ShipDateLocal") or row.get("ShipDate") or ""
    return str(value).split(" ", 1)[0]


def parse_ship_date(value):
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except (TypeError, ValueError):
        return None


def target_date_window():
    if TARGET_SHIP_DATE:
        target = parse_ship_date(TARGET_SHIP_DATE)
        if not target:
            raise RuntimeError("TARGET_SHIP_DATE must use MM/DD/YYYY, for example 05/21/2026.")
        return target, target

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=max(TARGET_DAYS, 1) - 1)
    return start_date, end_date


def should_keep_ship_date(value):
    ship_date = parse_ship_date(value)
    if not ship_date:
        return False
    start_date, end_date = target_date_window()
    return start_date <= ship_date <= end_date


def filter_records_by_target_dates(records):
    return [row for row in records if should_keep_ship_date(record_ship_date(row))]


def fetch_page(session, url, params):
    last_error = None
    for attempt in range(1, 4):
        try:
            response = session.get(url, params=params, timeout=60)
            print(f"GET {response.url}")
            print(f"Status: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            print(f"Request failed, attempt {attempt}/3: {exc}")
    raise last_error


def fetch_page_with_browser_context(page, url, params, headers):
    full_url = f"{url}?{urlencode(params)}"
    request_headers = {
        key: value
        for key, value in headers.items()
        if key.lower() not in ("host", "content-length")
    }
    last_error = None
    for attempt in range(1, 4):
        try:
            print(f"PLAYWRIGHT REQUEST GET {full_url}，attempt {attempt}/3")
            response = page.context.request.get(full_url, headers=request_headers, timeout=90000)
            text = response.text()
            print(f"Playwright request status: {response.status}")
            if not response.ok:
                raise RuntimeError(f"Tesla API 返回 {response.status}: {text[:500]}")
            return json.loads(text or "{}")
        except Exception as exc:
            last_error = exc
            print(f"Tesla API 请求失败，attempt {attempt}/3：{exc}", flush=True)
            time.sleep(5)
    raise last_error


def fetch_loadboard(local_storage=None, top=PAGE_SIZE, endpoint=DEFAULT_LOADBOARD_ENDPOINT, page=None, upload_url=None):
    if local_storage is None:
        local_storage = supplier_local_storage()
    if not valid_local_storage(local_storage):
        raise RuntimeError("特斯拉登录会话无效：未读取到可用 token，请先登录或重新保存会话。")
    captured_request = first_successful_loadboard_request()
    api_base = api_base_from_storage(local_storage)
    url = f"{api_base}/{endpoint}"
    headers = build_headers(captured_request, local_storage)
    params = default_params(local_storage, top=top, endpoint=endpoint)

    if not url.startswith("http"):
        raise RuntimeError(f"特斯拉 API 地址无效：{url}")

    session = requests.Session()
    session.headers.update(headers)

    if page is not None:
        first_payload = fetch_page_with_browser_context(page, url, params, headers)
    else:
        first_payload = fetch_page(session, url, params)
    records = flatten_records(first_payload)
    total = first_payload.get("Total") if isinstance(first_payload, dict) else None

    if isinstance(total, int) and total > len(records):
        for skip in range(top, total, top):
            page_params = dict(params)
            page_params["skip"] = skip
            page_payload = fetch_page_with_browser_context(page, url, page_params, headers) if page is not None else fetch_page(session, url, page_params)
            page_records = flatten_records(page_payload)
            if not page_records:
                break
            records.extend(page_records)

    records = dedupe_records(records)
    records = filter_records_by_target_dates(records)
    payload = dict(first_payload) if isinstance(first_payload, dict) else {"Data": records}
    payload["Data"] = records
    payload["FetchedEndpoint"] = endpoint
    payload["FetchedRowsAfterDedupe"] = len(records)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    write_csv(records)
    write_selected_csv(records)
    total_unique_rows = write_selected_all_csv(records)
    import_records = update_history(records)
    write_pending_changes_json(import_records)
    upload_result = upload_orders(upload_url, tpa_upload_orders(import_records))
    uploaded_marks = mark_uploaded_orders(upload_result)

    print(f"Saved JSON: {OUTPUT_JSON}")
    if records:
        print(f"Saved CSV: {OUTPUT_CSV}")
        print(f"Saved selected CSV: {OUTPUT_SELECTED_CSV}")
        print(f"Saved cumulative de-duplicated CSV: {OUTPUT_SELECTED_ALL_CSV}")
        print(f"Rows: {len(records)}")
        print(f"Cumulative unique rows: {total_unique_rows}")
        print(f"Local history need-upload rows: {len(import_records)}")
        print(f"Local history uploaded marks: {uploaded_marks}")
        print(f"Saved pending changes JSON: {OUTPUT_PENDING_CHANGES_JSON}")
    else:
        print("No list records detected for CSV export; JSON was saved.")
    print(f"Fetched at: {datetime.now().isoformat(timespec='seconds')}")
    start_date, end_date = target_date_window()
    print(f"Date filter: {start_date.strftime('%m/%d/%Y')} - {end_date.strftime('%m/%d/%Y')}")
    payload["UploadResult"] = upload_result
    payload["LocalHistoryNeedUploadRows"] = len(import_records)
    payload["LocalHistoryUploadedMarks"] = uploaded_marks
    return payload, records


def main():
    fetch_loadboard()


if __name__ == "__main__":
    main()
