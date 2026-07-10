from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ehx_guard.config import RuntimeConfig
from ehx_guard.database import Database
from ehx_guard.materials import Material, MaterialRepository
from ehx_guard.mii_client import (
    MiiClient,
    MiiUploadResult,
    _parse_response,
    build_s_code,
)
from ehx_guard.printing import PrintResult
from ehx_guard.scanner_service import ScannerService


MATERIAL_A = Material(
    "5664620-CLBK06", "主驾座椅背板总成 极夜黑", "566462001FA2", 2
)
MATERIAL_B = Material(
    "5664618-CLBK06", "副驾座椅背板总成 极夜黑", "566461801FA2", 5
)
BARCODE_A1 = "5664620-CLBK0620260616001"
BARCODE_A2 = "5664620-CLBK0620260616002"
BARCODE_A3 = "5664620-CLBK0620260616003"
BARCODE_B1 = "5664618-CLBK0620260616001"
BARCODE_B2 = "5664618-CLBK0620260616002"
MATERIAL_NEW = Material(
    "5664620FA2#01", "主驾座椅背板总成 极夜黑", "566462001FA2", 2
)
BARCODE_NEW1 = "5664620FA2#01#20260710#0060"
BARCODE_NEW2 = "5664620FA2#01#20260710#0061"


class FakePdfGenerator:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.labels = []

    def generate(self, label, output_path):
        self.labels.append(label)
        if self.fail:
            raise RuntimeError("模拟PDF失败")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n% fake logical test\n%%EOF\n")
        return path


class FakePrinter:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.paths = []

    def print_pdf(self, path):
        pdf_path = Path(path)
        self.paths.append(pdf_path)
        return PrintResult(
            success=self.success,
            pdf_path=pdf_path,
            printer_name="Fake Printer",
            message="ok" if self.success else "模拟打印失败",
        )


class FakeMii:
    def __init__(self, result=None) -> None:
        self.calls = []
        self.result = result or MiiUploadResult(
            True,
            status="PRODUCED",
            hu_code="1368123456965",
            s_code="123456965",
            message="PRODUCED",
        )

    def upload_offline_order(self, data):
        self.calls.append(data)
        return self.result


class ScannerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "data.db")
        self.database.upsert_materials([MATERIAL_A, MATERIAL_B])
        self.materials = MaterialRepository(
            self.database, self.root / "not-needed.xlsx"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self, box_count: int = 2) -> RuntimeConfig:
        return RuntimeConfig(
            box_scan_count=box_count,
            output_pdf_dir=str(self.root / "pdf"),
            database_path=str(self.root / "data.db"),
            material_excel_path=str(self.root / "not-needed.xlsx"),
            reserved1_sub="2918",
            mii_enabled=False,
        )

    def _service(
        self,
        *,
        box_count: int = 2,
        material_a_count: int | None = None,
        material_b_count: int | None = None,
        pdf=None,
        printer=None,
        mii=None,
    ) -> ScannerService:
        self.database.upsert_materials(
            [
                Material(
                    MATERIAL_A.material_code,
                    MATERIAL_A.material_name,
                    MATERIAL_A.customer_material_code,
                    material_a_count or box_count,
                ),
                Material(
                    MATERIAL_B.material_code,
                    MATERIAL_B.material_name,
                    MATERIAL_B.customer_material_code,
                    material_b_count or box_count,
                ),
            ]
        )
        self.materials.reload()
        return ScannerService(
            self._config(box_count),
            self.database,
            self.materials,
            pdf_generator=pdf or FakePdfGenerator(),
            printer=printer or FakePrinter(),
            mii_client=mii or FakeMii(),
        )

    def test_scan_guards_and_full_box_flow(self) -> None:
        pdf = FakePdfGenerator()
        printer = FakePrinter()
        mii = FakeMii()
        service = self._service(pdf=pdf, printer=printer, mii=mii)
        first_order = service.state.offline_order_no

        first = service.process_barcode(BARCODE_A1)
        self.assertTrue(first.accepted)
        self.assertEqual("5664620-CLBK06", first.state.material_code)
        self.assertEqual(1, first.state.scanned_count)

        duplicate = service.process_barcode(BARCODE_A1)
        self.assertFalse(duplicate.accepted)
        self.assertEqual("重复", duplicate.result)

        mixed = service.process_barcode(BARCODE_B1)
        self.assertFalse(mixed.accepted)
        self.assertEqual("物料不一致", mixed.result)

        unknown = service.process_barcode("9999999-UNKNOWN20260616001")
        self.assertFalse(unknown.accepted)
        self.assertEqual("未配置物料", unknown.result)

        completed = service.process_barcode(BARCODE_A2)
        self.assertTrue(completed.accepted)
        self.assertTrue(completed.box_completed)
        self.assertTrue(completed.printed)
        self.assertEqual("打印完成", completed.result)
        self.assertNotEqual(first_order, completed.state.offline_order_no)
        self.assertEqual(0, completed.state.scanned_count)

        self.assertEqual(1, len(pdf.labels))
        self.assertEqual("2918", pdf.labels[0].reserved1_sub)
        self.assertEqual("5664620-CLBK06", pdf.labels[0].material_code)
        self.assertRegex(pdf.labels[0].offline_order_no, r"^S\d{9}$")
        self.assertEqual(1, len(printer.paths))
        self.assertEqual(0, len(mii.calls))

        history = self.database.history_by_order(first_order)
        self.assertEqual(5, len(history))
        accepted = [row for row in history if row["result"] == "成功"]
        self.assertEqual(2, len(accepted))
        self.assertTrue(all(row["printed"] for row in accepted))
        self.assertGreaterEqual(
            len(self.database.history_by_barcode(BARCODE_A1)), 2
        )
        scan_date = history[0]["scan_time"][:10]
        self.assertGreaterEqual(
            len(self.database.history_by_date(scan_date)), 5
        )

    def test_invalid_and_empty_barcodes_do_not_increment(self) -> None:
        pdf = FakePdfGenerator()
        printer = FakePrinter()
        service = self._service(box_count=3, pdf=pdf, printer=printer)
        empty = service.process_barcode("")
        invalid = service.process_barcode("5664620-CLBK0620260230001")
        first = service.process_barcode(BARCODE_A1)
        self.assertEqual("格式错误", empty.result)
        self.assertEqual("格式错误", invalid.result)
        self.assertTrue(first.accepted)
        self.assertEqual(1, service.state.scanned_count)
        self.assertEqual([], pdf.labels)
        self.assertEqual([], printer.paths)

    def test_restart_recovers_incomplete_box(self) -> None:
        service = self._service(box_count=3)
        order_no = service.state.offline_order_no
        service.process_barcode(BARCODE_A1)

        restarted = ScannerService(
            self._config(3),
            self.database,
            MaterialRepository(
                self.database,
                self.root / "not-needed.xlsx",
                default_box_scan_count=3,
            ),
            pdf_generator=FakePdfGenerator(),
            printer=FakePrinter(),
            mii_client=FakeMii(),
        )
        self.assertEqual(order_no, restarted.state.offline_order_no)
        self.assertEqual(1, restarted.state.scanned_count)
        self.assertEqual("5664620-CLBK06", restarted.state.material_code)

    def test_pdf_failure_keeps_full_box_and_records(self) -> None:
        service = self._service(
            box_count=1, pdf=FakePdfGenerator(fail=True)
        )
        order_no = service.state.offline_order_no
        outcome = service.process_barcode(BARCODE_A1)
        self.assertEqual("PDF生成失败", outcome.result)
        self.assertEqual("PDF_FAILED", service.state.status)
        self.assertEqual(1, service.state.scanned_count)
        self.assertEqual(1, len(self.database.successful_scans(order_no)))

    def test_print_failure_keeps_pdf_and_current_box(self) -> None:
        service = self._service(
            box_count=1, printer=FakePrinter(success=False)
        )
        order_no = service.state.offline_order_no
        outcome = service.process_barcode(BARCODE_A1)
        order = self.database.get_order(order_no)
        self.assertEqual("打印失败", outcome.result)
        self.assertEqual("PRINT_FAILED", order["status"])
        self.assertTrue(Path(order["pdf_path"]).is_file())
        self.assertEqual(order_no, service.state.offline_order_no)

    def test_macos_debug_generates_pdf_only_and_starts_next_box(self) -> None:
        pdf = FakePdfGenerator()
        first_order = None
        self.database.upsert_materials(
            [
                Material(
                    MATERIAL_A.material_code,
                    MATERIAL_A.material_name,
                    MATERIAL_A.customer_material_code,
                    1,
                )
            ]
        )
        self.materials.reload()
        with patch("ehx_guard.scanner_service.platform.system", return_value="Darwin"):
            service = ScannerService(
                self._config(1),
                self.database,
                self.materials,
                pdf_generator=pdf,
                mii_client=FakeMii(),
            )
            first_order = service.state.offline_order_no
            outcome = service.process_barcode(BARCODE_A1)

        order = self.database.get_order(first_order)
        self.assertEqual("PDF已生成", outcome.result)
        self.assertFalse(outcome.printed)
        self.assertEqual("PDF_ONLY", order["status"])
        self.assertEqual(0, order["printed"])
        self.assertTrue(Path(order["pdf_path"]).is_file())
        self.assertNotEqual(first_order, service.state.offline_order_no)

    def test_different_materials_use_different_box_counts(self) -> None:
        service = self._service(
            box_count=99,
            material_a_count=2,
            material_b_count=5,
        )
        first_order = service.state.offline_order_no
        first = service.process_barcode(BARCODE_A1)
        self.assertEqual(2, first.state.required_count)
        service.process_barcode(BARCODE_A2)
        self.assertNotEqual(first_order, service.state.offline_order_no)

        second_material = service.process_barcode(BARCODE_B1)
        self.assertEqual(5, second_material.state.required_count)

    def test_required_count_is_frozen_on_historical_order(self) -> None:
        service = self._service(box_count=2, material_a_count=2)
        order_no = service.state.offline_order_no
        service.process_barcode(BARCODE_A1)
        self.assertEqual(
            2, self.database.get_order(order_no)["required_count"]
        )
        self.database.upsert_materials(
            [
                Material(
                    MATERIAL_A.material_code,
                    MATERIAL_A.material_name,
                    MATERIAL_A.customer_material_code,
                    44,
                )
            ]
        )
        self.assertEqual(
            2, self.database.get_order(order_no)["required_count"]
        )

    def test_reset_voids_records_and_allows_same_barcodes_again(self) -> None:
        service = self._service(box_count=44, material_a_count=44)
        old_order_no = service.state.offline_order_no
        for barcode in (BARCODE_A1, BARCODE_A2, BARCODE_A3):
            outcome = service.process_barcode(barcode)
            self.assertTrue(outcome.accepted)
        self.assertEqual(3, service.state.scanned_count)
        self.assertEqual(44, service.state.required_count)

        reset_state = service.reset_current_box()
        self.assertNotEqual(old_order_no, reset_state.offline_order_no)
        self.assertEqual("", reset_state.material_code)
        self.assertEqual(0, reset_state.scanned_count)
        self.assertEqual(44, reset_state.required_count)
        self.assertEqual("RESET", self.database.get_order(old_order_no)["status"])

        old_records = self.database.history_by_order(old_order_no)
        self.assertEqual(3, len(old_records))
        self.assertTrue(all(row["is_voided"] == 1 for row in old_records))
        self.assertTrue(
            all(row["void_reason"] == "manual reset" for row in old_records)
        )
        self.assertTrue(all(row["voided_at"] for row in old_records))

        rescanned = service.process_barcode(BARCODE_A1)
        self.assertTrue(rescanned.accepted)
        self.assertEqual(1, rescanned.state.scanned_count)
        barcode_history = self.database.history_by_barcode(BARCODE_A1)
        self.assertEqual(2, len(barcode_history))
        self.assertEqual(1, sum(not row["is_voided"] for row in barcode_history))

    def test_completed_box_cannot_be_reset(self) -> None:
        service = self._service(box_count=2)
        order_no = service.state.offline_order_no
        self.database.mark_printed(order_no)

        with self.assertRaisesRegex(
            ValueError,
            "已完成箱不能重置，请通过历史记录查看或补打",
        ):
            service.reset_current_box()

    def test_empty_box_can_be_reset_and_retry_remains_independent(self) -> None:
        service = self._service(box_count=6)
        old_order_no = service.state.offline_order_no

        state = service.reset_current_box()
        self.assertNotEqual(old_order_no, state.offline_order_no)
        self.assertEqual(0, state.scanned_count)
        self.assertEqual("RESET", self.database.get_order(old_order_no)["status"])

        retry = service.retry_current_box()
        self.assertEqual("未满箱", retry.result)

    def test_new_customer_barcode_format_uses_excel_prefix(self) -> None:
        self.database.upsert_materials([MATERIAL_NEW])
        self.materials.reload()
        service = self._service(
            box_count=2,
            material_a_count=2,
            pdf=FakePdfGenerator(),
            printer=FakePrinter(),
        )
        first = service.process_barcode(BARCODE_NEW1)
        self.assertTrue(first.accepted)
        self.assertEqual("5664620FA2#01", first.state.material_code)
        self.assertEqual("566462001FA2", first.state.customer_material_code)

    def test_mii_success_uses_s_code_on_printed_label(self) -> None:
        pdf = FakePdfGenerator()
        printer = FakePrinter()
        mii = FakeMii()
        service = ScannerService(
            RuntimeConfig(
                box_scan_count=2,
                output_pdf_dir=str(self.root / "pdf"),
                database_path=str(self.root / "data.db"),
                material_excel_path=str(self.root / "not-needed.xlsx"),
                reserved1_sub="2918",
                mii_enabled=True,
                mii_min_retry_interval_seconds=60,
                mii_max_retry_count=3,
            ),
            self.database,
            self.materials,
            pdf_generator=pdf,
            printer=printer,
            mii_client=mii,
        )
        order_no = service.state.offline_order_no

        service.process_barcode(BARCODE_A1)
        completed = service.process_barcode(BARCODE_A2)

        self.assertEqual("打印完成", completed.result)
        self.assertEqual(1, len(mii.calls))
        self.assertEqual("566462001FA2", mii.calls[0]["customer_material_code"])
        self.assertEqual(2, mii.calls[0]["required_count"])
        self.assertEqual("S123456965", pdf.labels[0].offline_order_no)
        order = self.database.get_order(order_no)
        self.assertEqual("1368123456965", order["mii_hu_code"])
        self.assertEqual("S123456965", order["mii_s_code"])
        self.assertEqual(
            2, len(self.database.history_by_hu("1368123456965"))
        )
        self.assertEqual(2, len(self.database.history_by_hu("S123456965")))
        self.assertEqual(2, len(self.database.history_by_hu("123456965")))

    def test_s_code_is_s_plus_last_nine_hu_digits(self) -> None:
        self.assertEqual("S123456965", build_s_code("1368123456965"))
        self.assertEqual("", build_s_code("12345678"))
        parsed = _parse_response(
            "<Status>PRODUCED</Status><HUCode>1368123456965</HUCode>"
        )
        self.assertTrue(parsed.success)
        self.assertEqual("S123456965", parsed.s_code)

    def test_mii_url_uses_config_and_dynamic_box_data(self) -> None:
        client = MiiClient(
            enabled=True,
            base_url="https://mii.example:50001/XMII/",
            login_name="zhangto",
            login_password="fau",
            plant="1680",
            user_id="zhangto",
            workcenter="WC00311",
            packaging_material="GENERIC_PACN",
            information="TEST",
        )
        query = parse_qs(
            urlsplit(
                client._build_url(
                    {
                        "offline_order_no": "INTERNAL-1",
                        "customer_material_code": "566462001FA2",
                        "required_count": 44,
                    }
                )
            ).query,
            keep_blank_values=True,
        )
        self.assertEqual(["566462001FA2"], query["PartNumber"])
        self.assertEqual(["44"], query["Quantity"])
        self.assertEqual(["WC00311"], query["Workcenter"])
        self.assertEqual(["TEST"], query["Information"])
        self.assertEqual([""], query["HUCode"])

    def test_mii_failure_stops_before_pdf_and_limits_retry(self) -> None:
        pdf = FakePdfGenerator()
        mii = FakeMii(
            MiiUploadResult(False, status="ERROR", message="模拟MII失败")
        )
        service = ScannerService(
            RuntimeConfig(
                box_scan_count=2,
                output_pdf_dir=str(self.root / "pdf"),
                database_path=str(self.root / "data.db"),
                material_excel_path=str(self.root / "not-needed.xlsx"),
                mii_enabled=True,
                mii_min_retry_interval_seconds=60,
                mii_max_retry_count=3,
            ),
            self.database,
            self.materials,
            pdf_generator=pdf,
            printer=FakePrinter(),
            mii_client=mii,
        )
        order_no = service.state.offline_order_no

        service.process_barcode(BARCODE_A1)
        failed = service.process_barcode(BARCODE_A2)
        retry = service.retry_current_box()

        self.assertEqual("MII报产失败", failed.result)
        self.assertEqual("MII报产失败", retry.result)
        self.assertEqual([], pdf.labels)
        self.assertEqual("MII_FAILED", self.database.get_order(order_no)["status"])
        self.assertEqual(order_no, service.state.offline_order_no)


if __name__ == "__main__":
    unittest.main()
