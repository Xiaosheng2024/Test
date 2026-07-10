"""扫码防错、满箱、PDF 和打印业务流程。"""

from __future__ import annotations

import logging
import platform
import socket
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .database import Database
from .materials import Material, MaterialRepository
from .mii_client import MiiClient, build_s_code
from .pdf_generator import A5PdfGenerator, OfflineOrderLabel
from .printing import (
    DebugNoPrintPrinter,
    ExcelComPrinter,
    PrintResult,
)


@dataclass(frozen=True)
class BoxState:
    offline_order_no: str
    box_no: str
    material_code: str
    material_name: str
    customer_material_code: str
    required_count: int
    scanned_count: int
    remaining_count: int
    status: str


@dataclass(frozen=True)
class ScanOutcome:
    accepted: bool
    result: str
    message: str
    barcode: str
    state: BoxState
    box_completed: bool = False
    printed: bool = False


class ScannerService:
    def __init__(
        self,
        config: RuntimeConfig,
        database: Database,
        materials: MaterialRepository,
        *,
        pdf_generator: A5PdfGenerator | Any | None = None,
        printer: ExcelComPrinter | Any | None = None,
        mii_client: MiiClient | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.database = database
        self.materials = materials
        # 每次程序启动同步一次 Excel；运行中可通过物料窗口手动重新导入。
        self.materials.load(refresh_from_excel=True)
        self.logger = logger or logging.getLogger("ehx_guard.scanner")
        self.computer_name = socket.gethostname()
        system_name = platform.system()
        if system_name == "Darwin":
            pdf_renderer = config.mac_pdf_renderer
        elif system_name == "Windows":
            pdf_renderer = config.windows_pdf_renderer
        else:
            pdf_renderer = "reportlab"
        self.pdf_generator = pdf_generator or A5PdfGenerator(
            config.template_path,
            enable_libreoffice=False,
            barcode_mode=config.barcode_mode,
            barcode_show_text=config.barcode_show_text,
            barcode_output_dir=config.barcode_output_dir,
            pdf_renderer=pdf_renderer,
        )
        if printer is not None:
            self.printer = printer
        elif system_name == "Darwin" and config.debug_no_print_on_mac:
            self.printer = DebugNoPrintPrinter(
                logger=getattr(self.pdf_generator, "logger", self.logger)
            )
        elif system_name == "Windows":
            self.printer = ExcelComPrinter(
                printer_name=config.printer_name,
                logger=getattr(self.pdf_generator, "logger", self.logger),
            )
        else:
            self.printer = DebugNoPrintPrinter(
                logger=getattr(self.pdf_generator, "logger", self.logger),
            )
        self.mii_client = mii_client or self._make_mii_client(config)
        self._order = self.database.get_recoverable_order()
        if self._order is None:
            self._order = self._create_next_order()

    def _make_mii_client(self, config: RuntimeConfig) -> MiiClient:
        return MiiClient(
            enabled=config.mii_enabled,
            base_url=config.mii_base_url,
            token=config.mii_token,
            transaction=config.mii_transaction,
            output_parameter=config.mii_output_parameter,
            login_name=config.mii_login_name,
            login_password=config.mii_login_password,
            plant=config.mii_plant,
            user_id=config.mii_user_id,
            customer_code=config.mii_customer_code,
            production_version=config.mii_production_version,
            production_shift=config.mii_production_shift,
            workcenter=config.mii_workcenter,
            packaging_material=config.mii_packaging_material,
            information_mode=config.mii_information_mode,
            information=config.mii_information,
            produce_reverse=config.mii_produce_reverse,
            content_type=config.mii_content_type,
            timeout_seconds=config.mii_timeout_seconds,
            logger=self.logger,
        )

    def apply_runtime_config(self, config: RuntimeConfig) -> None:
        """设置保存后立即更新打印机和 MII 客户端。"""

        self.config = config
        if hasattr(self.printer, "printer_name"):
            self.printer.printer_name = config.printer_name
        self.mii_client = self._make_mii_client(config)

    @property
    def state(self) -> BoxState:
        self._order = self.database.get_order(self._order["offline_order_no"])
        scanned = self.database.accepted_count(self._order["offline_order_no"])
        required = int(self._order["required_count"])
        return BoxState(
            offline_order_no=self._order["offline_order_no"],
            box_no=self._order["box_no"],
            material_code=self._order["material_code"],
            material_name=self._order["material_name"],
            customer_material_code=self._order["customer_material_code"],
            required_count=required,
            scanned_count=scanned,
            remaining_count=max(0, required - scanned),
            status=self._order["status"],
        )

    def process_barcode(self, raw_barcode: str) -> ScanOutcome:
        barcode = (raw_barcode or "").strip()
        current = self.state
        if current.status != "SCANNING":
            return ScanOutcome(
                False,
                "待处理",
                "当前箱已满或存在生成/打印失败，请先重试处理",
                barcode,
                current,
            )

        next_index = current.scanned_count + 1
        if not barcode:
            return self._reject("", next_index, "格式错误", "条码不能为空")

        material = self.materials.identify(barcode)
        if material is None:
            return self._reject(
                barcode, next_index, "未配置物料", "条码前缀不在物料配置表中"
            )

        valid, format_message = self.materials.validate_full_barcode(
            barcode, material
        )
        if not valid:
            return self._reject(
                barcode,
                next_index,
                "格式错误",
                format_message,
                material=material,
            )

        if self.database.accepted_barcode_exists(barcode):
            return self._reject(
                barcode,
                next_index,
                "重复",
                "该完整条码已经成功扫描",
                material=material,
            )

        if current.material_code and material.material_code != current.material_code:
            return self._reject(
                barcode,
                next_index,
                "物料不一致",
                f"当前箱物料为 {current.material_code}",
                material=material,
            )

        if not current.material_code:
            required_count = (
                material.box_scan_count or self.config.box_scan_count
            )
            self.database.set_order_material(
                current.offline_order_no,
                material.material_code,
                material.material_name,
                material.customer_material_code,
                required_count,
            )

        try:
            self._record(
                barcode=barcode,
                scan_index=next_index,
                result="成功",
                message="扫码成功",
                material=material,
            )
        except sqlite3.IntegrityError:
            return self._reject(
                barcode,
                next_index,
                "重复",
                "该完整条码已经成功扫描",
                material=material,
            )

        updated = self.state
        if updated.scanned_count < updated.required_count:
            return ScanOutcome(
                True, "成功", "扫码成功", barcode, updated
            )
        return self._finalize_current_box(barcode)

    def retry_current_box(self) -> ScanOutcome:
        return self._finalize_current_box("")

    def reset_current_box(
        self, reason: str = "manual reset"
    ) -> BoxState:
        """逻辑作废当前未完成箱，并以相同目标数量初始化空箱。"""

        current = self.state
        order = self.database.get_order(current.offline_order_no)
        if int(order["printed"]) or order["status"] in {
            "PRINTED",
            "PDF_ONLY",
        }:
            raise ValueError(
                "已完成箱不能重置，请通过历史记录查看或补打。"
            )

        voided_count = self.database.reset_order(
            current.offline_order_no,
            reason=reason,
        )
        self.logger.warning(
            "当前箱已重置：order=%s voided_records=%s reason=%s",
            current.offline_order_no,
            voided_count,
            reason,
        )
        self._order = self._create_next_order(current.required_count)
        return self.state

    def reprint(self, offline_order_no: str) -> PrintResult:
        order = self.database.get_order(offline_order_no)
        pdf_path = Path(order["pdf_path"])
        result = self.printer.print_pdf(pdf_path)
        if result.success and not result.skipped:
            self.database.mark_printed(offline_order_no, reprint=True)
        elif not result.success:
            self.database.update_order_status(
                offline_order_no,
                "PRINT_FAILED",
                print_error=result.message,
            )
        return result

    def _reject(
        self,
        barcode: str,
        scan_index: int,
        result: str,
        message: str,
        *,
        material: Material | None = None,
    ) -> ScanOutcome:
        self._record(
            barcode=barcode,
            scan_index=scan_index,
            result=result,
            message=message,
            material=material,
        )
        return ScanOutcome(False, result, message, barcode, self.state)

    def _record(
        self,
        *,
        barcode: str,
        scan_index: int,
        result: str,
        message: str,
        material: Material | None,
    ) -> None:
        current = self.state
        self.database.record_scan(
            offline_order_no=current.offline_order_no,
            box_no=current.box_no,
            barcode=barcode,
            scan_index=scan_index,
            result=result,
            message=message,
            material_code=material.material_code if material else "",
            material_name=material.material_name if material else "",
            customer_material_code=(
                material.customer_material_code if material else ""
            ),
            computer_name=self.computer_name,
            line_name=self.config.line_name,
            station_name=self.config.station_name,
        )

    def _finalize_current_box(self, triggering_barcode: str) -> ScanOutcome:
        current = self.state
        if not current.material_code or current.required_count <= 0:
            return ScanOutcome(
                False,
                "未满箱",
                "请先扫描第一件以识别物料和每箱数量",
                triggering_barcode,
                current,
            )
        if current.scanned_count != current.required_count:
            return ScanOutcome(
                False,
                "未满箱",
                f"还需扫描 {current.remaining_count} 件",
                triggering_barcode,
                current,
            )

        order = self.database.get_order(current.offline_order_no)
        if self.config.mii_enabled and not order.get("mii_s_code"):
            mii_outcome = self._upload_mii_once(order, triggering_barcode)
            if mii_outcome is not None:
                return mii_outcome
            order = self.database.get_order(current.offline_order_no)

        pdf_path = Path(order["pdf_path"]) if order["pdf_path"] else None
        if pdf_path is None or not pdf_path.is_file():
            output_dir = Path(self.config.output_pdf_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = output_dir / f"{current.offline_order_no}.pdf"
            # 客户批次/下线单优先来自 MII HU；MII 未启用或未返回时，
            # 本地生成一个同样符合 S+9位数字 规则的批次号，避免条码为空。
            print_order_no = order.get("mii_s_code") or ""
            if not print_order_no:
                print_order_no = f"S{int(order['id']):09d}"
                self.database.set_local_s_code(
                    current.offline_order_no, print_order_no
                )
            label = OfflineOrderLabel(
                offline_order_no=print_order_no,
                material_code=current.material_code,
                material_name=current.material_name,
                customer_material_code=current.customer_material_code,
                quantity=current.required_count,
                production_time=datetime.now(),
                offline_location=self.config.station_name,
                reserved1_sub=self.config.reserved1_sub,
            )
            try:
                self.database.update_order_status(
                    current.offline_order_no, "PDF_GENERATING"
                )
                self.pdf_generator.generate(label, pdf_path)
                self.database.update_order_status(
                    current.offline_order_no,
                    "READY_TO_PRINT",
                    pdf_path=str(pdf_path.resolve()),
                    print_error="",
                )
            except Exception as exc:
                message = f"PDF生成失败：{exc}"
                self.logger.exception(message)
                self.database.update_order_status(
                    current.offline_order_no,
                    "PDF_FAILED",
                    print_error=message,
                )
                return ScanOutcome(
                    True,
                    "PDF生成失败",
                    message,
                    triggering_barcode,
                    self.state,
                    box_completed=True,
                )

        print_result = self.printer.print_pdf(pdf_path)
        if not print_result.success:
            self.database.update_order_status(
                current.offline_order_no,
                "PRINT_FAILED",
                pdf_path=str(pdf_path.resolve()),
                print_error=print_result.message,
            )
            return ScanOutcome(
                True,
                "打印失败",
                f"打印失败，PDF和数据已保留：{print_result.message}",
                triggering_barcode,
                self.state,
                box_completed=True,
            )

        if print_result.skipped:
            self.database.update_order_status(
                current.offline_order_no,
                "PDF_ONLY",
                pdf_path=str(pdf_path.resolve()),
                print_error="",
            )
        else:
            self.database.mark_printed(current.offline_order_no)
        self._order = self._create_next_order()
        result_name = "PDF已生成" if print_result.skipped else "打印完成"
        result_message = (
            "PDF已生成，macOS调试模式已跳过打印"
            if print_result.skipped
            else "PDF已生成，打印已发送"
        )
        return ScanOutcome(
            True,
            result_name,
            result_message,
            triggering_barcode,
            self.state,
            box_completed=True,
            printed=not print_result.skipped,
        )

    def _upload_mii_once(
        self, order: dict[str, Any], triggering_barcode: str
    ) -> ScanOutcome | None:
        if not self._mii_retry_allowed(order):
            return ScanOutcome(
                True,
                "MII报产失败",
                order.get("print_error")
                or order.get("mii_error")
                or "MII重试过于频繁或次数已达上限",
                triggering_barcode,
                self.state,
                box_completed=True,
            )

        self.database.mark_mii_attempt(order["offline_order_no"])
        upload_data = {
            **self.database.get_order(order["offline_order_no"]),
            "barcodes": [
                row["barcode"]
                for row in self.database.successful_scans(
                    order["offline_order_no"]
                )
            ],
        }
        result = self.mii_client.upload_offline_order(upload_data)
        hu_code = str(getattr(result, "hu_code", "") or "").strip()
        s_code = build_s_code(hu_code)
        success = bool(getattr(result, "success", result is True)) and bool(
            s_code
        )
        message = str(getattr(result, "message", "") or "")
        if not s_code and hu_code:
            message = "MII返回的HUCode不足9位，已停止打印"
        self.database.mark_mii_result(
            order["offline_order_no"],
            success=success,
            status=getattr(result, "status", ""),
            hu_code=hu_code,
            s_code=s_code,
            message=message,
            raw_response=getattr(result, "raw_response", ""),
        )
        if success:
            return None
        return ScanOutcome(
            True,
            "MII报产失败",
            f"MII报产失败，已停止打印并保留当前箱：{message}",
            triggering_barcode,
            self.state,
            box_completed=True,
        )

    def _mii_retry_allowed(self, order: dict[str, Any]) -> bool:
        attempts = int(order.get("mii_attempt_count") or 0)
        if attempts >= self.config.mii_max_retry_count:
            self.database.update_order_status(
                order["offline_order_no"],
                "MII_FAILED",
                print_error=(
                    f"MII报产失败次数已达上限 "
                    f"{self.config.mii_max_retry_count}，请联系管理员"
                ),
            )
            return False
        last_attempt = order.get("mii_last_attempt_at")
        if last_attempt:
            try:
                last_time = datetime.fromisoformat(last_attempt)
                elapsed = (
                    datetime.now().astimezone() - last_time
                ).total_seconds()
            except ValueError:
                elapsed = self.config.mii_min_retry_interval_seconds
            if elapsed < self.config.mii_min_retry_interval_seconds:
                wait = int(self.config.mii_min_retry_interval_seconds - elapsed)
                self.database.update_order_status(
                    order["offline_order_no"],
                    "MII_FAILED",
                    print_error=f"MII重试过于频繁，请 {wait} 秒后再试",
                )
                return False
        return True

    def _create_next_order(
        self, initial_required_count: int = 0
    ) -> dict[str, Any]:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        return self.database.create_order(
            f"EHX{stamp}",
            f"BOX{stamp}",
            max(0, int(initial_required_count)),
        )
