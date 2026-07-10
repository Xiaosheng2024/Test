"""程序 JSON 配置读取。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class RuntimeConfig:
    printer_name: str = ""
    scanner_mode: str = "serial"
    serial_port: str = ""
    serial_baudrate: int = 9600
    hid_force_english: bool = True
    hid_capture_without_input_focus: bool = True
    template_path: str = "报交下线单模板.xlsx"
    output_pdf_dir: str = "output/pdf"
    database_path: str = "data/ehx_guard.db"
    reserved1_sub: str = "2918"
    box_scan_count: int = 6
    line_name: str = "EHX"
    station_name: str = "下线工位"
    material_excel_path: str = "EHX物料号匹配.xlsx"
    mii_enabled: bool = False
    mii_base_url: str = ""
    mii_token: str = ""
    mii_transaction: str = (
        "SC_AUTOMATION/API/PRODUCTION/V1/TRANSACTION/PRODUCTION_API"
    )
    mii_output_parameter: str = "ResultXML"
    mii_login_name: str = ""
    mii_login_password: str = ""
    mii_plant: str = ""
    mii_user_id: str = ""
    mii_customer_code: str = ""
    mii_production_version: str = "0001"
    mii_production_shift: str = ""
    mii_workcenter: str = ""
    mii_packaging_material: str = ""
    mii_information_mode: str = "offline_order_no"
    mii_information: str = ""
    mii_produce_reverse: str = "P"
    mii_content_type: str = "text/xml"
    mii_timeout_seconds: int = 10
    mii_min_retry_interval_seconds: int = 60
    mii_max_retry_count: int = 3
    barcode_mode: str = "image"
    barcode_show_text: bool = True
    barcode_output_dir: str = "output/barcodes"
    pdf_renderer: str = "excel_com"
    print_method: str = "excel_com"
    debug_no_print_on_mac: bool = True
    mac_pdf_renderer: str = "reportlab"
    windows_pdf_renderer: str = "excel_com"
    windows_print_method: str = "excel_com"


def load_config(path: str | Path = "config.json") -> RuntimeConfig:
    config_path = Path(path)
    if not config_path.is_file():
        return RuntimeConfig()
    with config_path.open("r", encoding="utf-8") as source:
        raw = json.load(source)
    if not isinstance(raw, dict):
        raise ValueError("config.json 顶层必须是 JSON 对象")
    defaults = RuntimeConfig()
    return RuntimeConfig(
        printer_name=str(raw.get("printer_name", defaults.printer_name)).strip(),
        scanner_mode=(
            str(raw.get("scanner_mode", defaults.scanner_mode)).strip().lower()
            if str(raw.get("scanner_mode", defaults.scanner_mode)).strip().lower()
            in {"hid", "serial"}
            else defaults.scanner_mode
        ),
        serial_port=str(raw.get("serial_port", defaults.serial_port)).strip(),
        serial_baudrate=max(
            1, int(raw.get("serial_baudrate", defaults.serial_baudrate))
        ),
        hid_force_english=bool(
            raw.get("hid_force_english", defaults.hid_force_english)
        ),
        hid_capture_without_input_focus=bool(
            raw.get(
                "hid_capture_without_input_focus",
                defaults.hid_capture_without_input_focus,
            )
        ),
        template_path=str(
            raw.get("template_path", defaults.template_path)
        ).strip(),
        output_pdf_dir=str(
            raw.get("output_pdf_dir", defaults.output_pdf_dir)
        ).strip(),
        database_path=str(
            raw.get("database_path", defaults.database_path)
        ).strip(),
        reserved1_sub=str(
            raw.get("reserved1_sub", defaults.reserved1_sub)
        ).strip()
        or defaults.reserved1_sub,
        box_scan_count=max(
            1, int(raw.get("box_scan_count", defaults.box_scan_count))
        ),
        line_name=str(raw.get("line_name", defaults.line_name)).strip(),
        station_name=str(raw.get("station_name", defaults.station_name)).strip(),
        material_excel_path=str(
            raw.get("material_excel_path", defaults.material_excel_path)
        ).strip(),
        mii_enabled=bool(raw.get("mii_enabled", defaults.mii_enabled)),
        mii_base_url=str(
            raw.get("mii_base_url", defaults.mii_base_url)
        ).strip(),
        mii_token=str(raw.get("mii_token", defaults.mii_token)).strip(),
        mii_transaction=str(
            raw.get("mii_transaction", defaults.mii_transaction)
        ).strip()
        or defaults.mii_transaction,
        mii_output_parameter=str(
            raw.get("mii_output_parameter", defaults.mii_output_parameter)
        ).strip()
        or defaults.mii_output_parameter,
        mii_login_name=str(
            raw.get("mii_login_name", defaults.mii_login_name)
        ).strip(),
        mii_login_password=str(
            raw.get("mii_login_password", defaults.mii_login_password)
        ).strip(),
        mii_plant=str(raw.get("mii_plant", defaults.mii_plant)).strip(),
        mii_user_id=str(
            raw.get("mii_user_id", defaults.mii_user_id)
        ).strip(),
        mii_customer_code=str(
            raw.get("mii_customer_code", defaults.mii_customer_code)
        ).strip(),
        mii_production_version=str(
            raw.get(
                "mii_production_version",
                defaults.mii_production_version,
            )
        ).strip(),
        mii_production_shift=str(
            raw.get(
                "mii_production_shift",
                defaults.mii_production_shift,
            )
        ).strip(),
        mii_workcenter=str(
            raw.get("mii_workcenter", defaults.mii_workcenter)
        ).strip(),
        mii_packaging_material=str(
            raw.get(
                "mii_packaging_material",
                defaults.mii_packaging_material,
            )
        ).strip(),
        mii_information_mode=str(
            raw.get(
                "mii_information_mode",
                defaults.mii_information_mode,
            )
        ).strip(),
        mii_information=str(
            raw.get("mii_information", defaults.mii_information)
        ).strip(),
        mii_produce_reverse=str(
            raw.get("mii_produce_reverse", defaults.mii_produce_reverse)
        ).strip()
        or defaults.mii_produce_reverse,
        mii_content_type=str(
            raw.get("mii_content_type", defaults.mii_content_type)
        ).strip()
        or defaults.mii_content_type,
        mii_timeout_seconds=max(
            1,
            int(
                raw.get(
                    "mii_timeout_seconds",
                    defaults.mii_timeout_seconds,
                )
            ),
        ),
        mii_min_retry_interval_seconds=max(
            0,
            int(
                raw.get(
                    "mii_min_retry_interval_seconds",
                    defaults.mii_min_retry_interval_seconds,
                )
            ),
        ),
        mii_max_retry_count=max(
            1,
            int(
                raw.get(
                    "mii_max_retry_count",
                    defaults.mii_max_retry_count,
                )
            ),
        ),
        barcode_mode=str(
            raw.get("barcode_mode", defaults.barcode_mode)
        ).strip().lower(),
        barcode_show_text=bool(
            raw.get("barcode_show_text", defaults.barcode_show_text)
        ),
        barcode_output_dir=str(
            raw.get("barcode_output_dir", defaults.barcode_output_dir)
        ).strip(),
        pdf_renderer=str(
            raw.get("pdf_renderer", defaults.pdf_renderer)
        ).strip().lower(),
        print_method=str(
            raw.get("print_method", defaults.print_method)
        ).strip().lower(),
        debug_no_print_on_mac=bool(
            raw.get(
                "debug_no_print_on_mac",
                defaults.debug_no_print_on_mac,
            )
        ),
        mac_pdf_renderer=str(
            raw.get("mac_pdf_renderer", defaults.mac_pdf_renderer)
        ).strip().lower(),
        windows_pdf_renderer=str(
            raw.get(
                "windows_pdf_renderer", defaults.windows_pdf_renderer
            )
        ).strip().lower(),
        windows_print_method=str(
            raw.get(
                "windows_print_method", defaults.windows_print_method
            )
        ).strip().lower(),
    )


def update_config(path: str | Path, **updates: object) -> RuntimeConfig:
    """原子更新指定配置项，保留 MII 等其他已有字段。"""

    config_path = Path(path)
    raw: dict[str, object] = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as source:
            loaded = json.load(source)
        if not isinstance(loaded, dict):
            raise ValueError("config.json 顶层必须是 JSON 对象")
        raw.update(loaded)
    raw.update(updates)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=config_path.parent,
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as target:
        json.dump(raw, target, ensure_ascii=False, indent=2)
        target.write("\n")
        temporary_path = Path(target.name)
    try:
        temporary_path.replace(config_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return load_config(config_path)
