"""EHX 下线防错程序 PySide6 全屏界面。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import platform
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import RuntimeConfig, load_config, update_config
from .database import Database
from .materials import MaterialRepository
from .scanner_input import (
    HidScanFilter,
    SerialScanner,
    available_serial_ports,
    force_windows_english_layout,
)
from .scanner_service import BoxState, ScannerService


STATUS_COLORS = {
    "待扫码": "#334155",
    "成功": "#15803d",
    "重复": "#b91c1c",
    "物料不一致": "#b91c1c",
    "格式错误": "#b91c1c",
    "未配置物料": "#b91c1c",
    "PDF生成失败": "#b91c1c",
    "打印失败": "#b45309",
    "打印完成": "#0369a1",
    "PDF已生成": "#0369a1",
}


class ErrorPopup(QDialog):
    """产线用非阻塞错误提示窗。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("扫码错误")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(620)
        self.setStyleSheet(
            "QDialog { background: #fff7ed; border: 5px solid #b91c1c; }"
            "QLabel { color: #991b1b; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(
            QFont("Microsoft YaHei", 28, QFont.Weight.Bold)
        )
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setFont(QFont("Microsoft YaHei", 20))
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)

    def set_error(self, title: str, message: str) -> None:
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.adjustSize()

    def text(self) -> str:
        return self.title_label.text()


class MainWindow(QWidget):
    def __init__(
        self,
        service: ScannerService,
        config_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.config_path = Path(
            config_path or getattr(service, "config_path", "config.json")
        )
        self.error_dialog: ErrorPopup | None = None
        self.error_close_timer = QTimer(self)
        self.error_close_timer.setSingleShot(True)
        self.error_close_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.error_close_timer.setInterval(3000)
        self.error_close_timer.timeout.connect(self._close_error_popup)
        self.setWindowTitle("EHX 下线防错程序")
        self.setStyleSheet(
            "QWidget { background: #f1f5f9; color: #0f172a; }"
            "QLineEdit { background: white; border: 3px solid #2563eb;"
            " border-radius: 8px; padding: 12px; }"
            "QPushButton { background: #1d4ed8; color: white; padding: 12px;"
            " border-radius: 7px; font-size: 18px; }"
            "QTableWidget { background: white; font-size: 15px; }"
        )
        self._build_ui()
        self._install_shortcuts()
        self.hid_scanner = HidScanFilter()
        self.hid_scanner.barcode_received.connect(self._submit_barcode)
        self.hid_scanner.preview_changed.connect(self.scan_input.setText)
        QApplication.instance().installEventFilter(self.hid_scanner)
        self.serial_scanner = SerialScanner()
        self.serial_scanner.barcode_received.connect(self._submit_barcode)
        self.serial_scanner.connection_error.connect(
            lambda message: self.show_error_popup("串口连接失败", message)
        )
        self._apply_scanner_config(show_error=True)
        self._refresh_state()
        self._refresh_recent()
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self._ensure_scan_focus)
        self.focus_timer.start(800)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(14)

        self.title_row = QHBoxLayout()
        title = QLabel("EHX 下线防错")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        self.title_row.addWidget(title)
        mode_text = (
            "macOS 调试模式：只生成PDF，不打印"
            if platform.system() == "Darwin"
            else "Windows 正式模式：生成PDF并打印"
        )
        mode_label = QLabel(mode_text)
        mode_label.setStyleSheet(
            "background: #dbeafe; color: #1e3a8a; padding: 10px;"
            " border-radius: 8px;"
        )
        mode_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        self.title_row.addWidget(mode_label)
        self.title_row.addStretch(1)
        self.progress_big_label = QLabel("0/0")
        self.progress_big_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_big_label.setMinimumWidth(240)
        self.progress_big_label.setFont(
            QFont("Arial", 56, QFont.Weight.Black)
        )
        self.progress_big_label.setStyleSheet(
            "background: #ffffff; color: #0f172a;"
            " border: 3px solid #0f172a; border-radius: 12px;"
            " padding: 2px 18px;"
        )
        materials_button = QPushButton("物料查看 / 重新导入")
        materials_button.clicked.connect(self._open_materials)
        history_button = QPushButton("历史查询 / 补打")
        history_button.clicked.connect(self._open_history)
        retry_button = QPushButton("重试满箱处理")
        retry_button.clicked.connect(self._retry_finalize)
        self.reset_button = QPushButton("重置当前箱")
        self.reset_button.clicked.connect(self._confirm_reset_current_box)
        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self._open_settings)
        self.title_row.addWidget(materials_button)
        self.title_row.addWidget(history_button)
        self.title_row.addWidget(retry_button)
        self.title_row.addWidget(self.reset_button)
        self.title_row.addWidget(self.settings_button)
        root.addLayout(self.title_row)

        # 复用同一个大号进度控件，放在顶部按钮下方的右侧中上区域。
        self.progress_row = QHBoxLayout()
        self.progress_row.addStretch(3)
        self.progress_row.addWidget(
            self.progress_big_label,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self.progress_row.addStretch(1)
        root.addLayout(self.progress_row)

        info = QGridLayout()
        info.setSpacing(12)
        self.material_value = self._card(info, 0, 0, "当前物料", "--", 3)
        self.required_value = self._card(info, 1, 0, "需扫数量", "0")
        self.scanned_value = self._card(info, 1, 1, "已扫数量", "0")
        self.remaining_value = self._card(info, 1, 2, "剩余数量", "0")
        root.addLayout(info)

        self.status_label = QLabel("待扫码")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(
            QFont("Microsoft YaHei", 30, QFont.Weight.Bold)
        )
        self.status_label.setMinimumHeight(72)
        root.addWidget(self.status_label)

        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("请扫描条码（扫码后自动回车处理）")
        self.scan_input.setFont(QFont("Consolas", 24))
        self.scan_input.returnPressed.connect(self._process_scan)
        root.addWidget(self.scan_input)

        recent_title = QLabel("最近扫码")
        recent_title.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        root.addWidget(recent_title)
        self.recent_table = QTableWidget(0, 5)
        self.recent_table.setHorizontalHeaderLabels(
            ["时间", "完整条码", "物料号", "结果", "说明"]
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.recent_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.recent_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        root.addWidget(self.recent_table, 1)

    def _card(
        self,
        layout: QGridLayout,
        row: int,
        column: int,
        caption: str,
        value: str,
        column_span: int = 1,
    ) -> QLabel:
        card = QWidget()
        card.setStyleSheet(
            "background: white; border: 1px solid #cbd5e1; border-radius: 10px;"
        )
        box = QVBoxLayout(card)
        label = QLabel(caption)
        label.setFont(QFont("Microsoft YaHei", 14))
        output = QLabel(value)
        output.setWordWrap(True)
        output.setFont(QFont("Microsoft YaHei", 27, QFont.Weight.Bold))
        box.addWidget(label)
        box.addWidget(output)
        layout.addWidget(card, row, column, 1, column_span)
        return output

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

    def _process_scan(self) -> None:
        self._submit_barcode(self.scan_input.text())

    def _submit_barcode(self, barcode: str) -> None:
        previous_state = self.service.state
        self.scan_input.clear()
        outcome = self.service.process_barcode(barcode)
        self._show_status(outcome.result, outcome.message)
        self._handle_outcome_error(outcome)
        self._refresh_outcome_state(previous_state, outcome)
        self._refresh_recent()
        self.scan_input.setFocus()

    def _retry_finalize(self) -> None:
        previous_state = self.service.state
        outcome = self.service.retry_current_box()
        self._show_status(outcome.result, outcome.message)
        self._handle_outcome_error(outcome)
        self._refresh_outcome_state(previous_state, outcome)
        self._refresh_recent()

    def _confirm_reset_current_box(self) -> None:
        self.serial_scanner.stop()
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("重置当前箱")
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setText(
            "确认要重置当前箱吗？\n"
            "当前已扫码记录将作废，本箱将从 0 重新开始。"
        )
        confirm_button = confirmation.addButton(
            "确认重置",
            QMessageBox.ButtonRole.AcceptRole,
        )
        confirmation.addButton(
            "取消",
            QMessageBox.ButtonRole.RejectRole,
        )
        confirmation.exec()
        if confirmation.clickedButton() is not confirm_button:
            self._apply_scanner_config(show_error=True)
            self.scan_input.setFocus()
            return

        try:
            state = self.service.reset_current_box("manual reset")
        except (KeyError, ValueError, RuntimeError) as exc:
            self._apply_scanner_config(show_error=True)
            QApplication.beep()
            self.show_error_popup("重置当前箱失败", str(exc))
            return

        self._refresh_state(state)
        self._refresh_recent()
        self._show_status("待扫码", "当前箱已重置，请重新扫码")
        self._apply_scanner_config(show_error=True)
        self.scan_input.clear()
        self.scan_input.setFocus()

    def _show_status(self, result: str, message: str) -> None:
        color = STATUS_COLORS.get(result, STATUS_COLORS["待扫码"])
        self.status_label.setText(f"{result}：{message}")
        self.status_label.setStyleSheet(
            f"background: {color}; color: white; border-radius: 10px;"
        )

    def _refresh_state(self, state: BoxState | None = None) -> None:
        state = state or self.service.state
        material = state.material_code or "等待首件扫码"
        if state.material_name:
            material += f"\n{state.material_name}"
        self.material_value.setText(material)
        required_text = (
            str(state.required_count) if state.required_count > 0 else "--"
        )
        remaining_text = (
            str(state.remaining_count) if state.required_count > 0 else "--"
        )
        self.required_value.setText(required_text)
        self.scanned_value.setText(str(state.scanned_count))
        self.remaining_value.setText(remaining_text)
        self.progress_big_label.setText(
            f"{state.scanned_count}/{required_text}"
        )
        if state.status != "SCANNING":
            self._show_status(state.status, "当前箱需要处理")

    def _refresh_recent(self) -> None:
        rows = self.service.database.recent_records(10)
        self.recent_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            is_voided = bool(row.get("is_voided", 0))
            values = [
                row["scan_time"][11:19],
                row["barcode"],
                row["material_code"],
                "已作废" if is_voided else row["result"],
                (
                    f"{row.get('void_reason', '')}（已重置）"
                    if is_voided
                    else row["message"]
                ),
            ]
            for column, value in enumerate(values):
                self.recent_table.setItem(
                    row_index, column, QTableWidgetItem(str(value))
                )

    def _refresh_outcome_state(self, previous_state: BoxState, outcome: object) -> None:
        switched_to_new_box = (
            outcome.box_completed
            and outcome.state.offline_order_no
            != previous_state.offline_order_no
        )
        if not switched_to_new_box:
            self._refresh_state(outcome.state)
            return

        completed_order = self.service.database.get_order(
            previous_state.offline_order_no
        )
        completed_required = int(completed_order["required_count"])
        completed_state = replace(
            previous_state,
            material_code=completed_order["material_code"],
            material_name=completed_order["material_name"],
            customer_material_code=completed_order[
                "customer_material_code"
            ],
            required_count=completed_required,
            scanned_count=completed_required,
            remaining_count=0,
        )
        self._refresh_state(completed_state)
        next_order_no = outcome.state.offline_order_no
        QTimer.singleShot(
            800,
            lambda: self._refresh_new_box_if_still_empty(next_order_no),
        )

    def _refresh_new_box_if_still_empty(self, order_no: str) -> None:
        current = self.service.state
        if (
            current.offline_order_no == order_no
            and current.scanned_count == 0
        ):
            self._refresh_state(current)

    def _open_history(self) -> None:
        self.hid_scanner.paused = True
        self.serial_scanner.stop()
        HistoryDialog(self.service, self).exec()
        self.hid_scanner.paused = False
        self._apply_scanner_config(show_error=True)
        self.scan_input.setFocus()

    def _open_materials(self) -> None:
        self.hid_scanner.paused = True
        self.serial_scanner.stop()
        MaterialDialog(self.service, self).exec()
        self.hid_scanner.paused = False
        self._apply_scanner_config(show_error=True)
        self.scan_input.setFocus()

    def _open_settings(self) -> None:
        self.hid_scanner.paused = True
        self.serial_scanner.stop()
        dialog = SettingsDialog(self.service.config, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self.hid_scanner.paused = False
        if not accepted:
            self._apply_scanner_config(show_error=True)
            self.scan_input.setFocus()
            return
        values = dialog.values()
        try:
            update_config(self.config_path, **values)
        except (OSError, TypeError, ValueError) as exc:
            self.show_error_popup("设置保存失败", str(exc))
            self._apply_scanner_config(show_error=True)
            return
        self.service.apply_runtime_config(
            replace(self.service.config, **values)
        )
        self._apply_scanner_config(show_error=True)
        QMessageBox.information(self, "设置", "设置已保存并立即生效")
        self.scan_input.setFocus()

    def _apply_scanner_config(self, *, show_error: bool) -> None:
        config = self.service.config
        self.hid_scanner.clear()
        self.hid_scanner.enabled = (
            config.scanner_mode == "hid"
            and config.hid_capture_without_input_focus
        )
        self.serial_scanner.stop()
        if config.scanner_mode == "hid":
            self.scan_input.setPlaceholderText(
                "HID扫码模式：无需将光标放在输入框"
            )
            if config.hid_force_english:
                force_windows_english_layout()
            return
        self.scan_input.setPlaceholderText(
            f"串口扫码模式：{config.serial_port or '未配置端口'}"
        )
        try:
            self.serial_scanner.start(
                config.serial_port,
                config.serial_baudrate,
            )
        except (RuntimeError, ValueError) as exc:
            self.serial_scanner.logger.error("%s", exc)
            if show_error:
                self.show_error_popup("串口连接失败", str(exc))

    def _ensure_scan_focus(self) -> None:
        if QApplication.activeModalWidget() is None:
            self.scan_input.setFocus()

    def _handle_outcome_error(self, outcome: object) -> None:
        error_results = {
            "重复",
            "物料不一致",
            "格式错误",
            "未配置物料",
            "PDF生成失败",
            "打印失败",
            "待处理",
            "未满箱",
        }
        if not outcome.accepted or outcome.result in error_results:
            QApplication.beep()
            self.show_error_popup(outcome.result, outcome.message)

    def show_error_popup(self, title: str, message: str) -> None:
        """显示非阻塞错误窗口；新错误会更新内容并重置3秒计时。"""

        if self.error_dialog is None:
            self.error_dialog = ErrorPopup(self)
        self.error_dialog.set_error(title, message)
        self.error_dialog.show()
        self.error_dialog.raise_()
        self.error_close_timer.start()
        QTimer.singleShot(0, self._restore_scan_focus)

    def _close_error_popup(self) -> None:
        if self.error_dialog is not None:
            self.error_dialog.close()
        self._restore_scan_focus()

    def _restore_scan_focus(self) -> None:
        self.activateWindow()
        self.scan_input.setFocus()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ActivationChange
            and self.isActiveWindow()
            and self.service.config.scanner_mode == "hid"
            and self.service.config.hid_force_english
        ):
            force_windows_english_layout()

    def closeEvent(self, event: QEvent) -> None:
        self.serial_scanner.stop()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self.hid_scanner)
        super().closeEvent(event)


class SettingsDialog(QDialog):
    """打印机和扫码枪设置。"""

    def __init__(
        self,
        config: RuntimeConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        self.resize(820, 720)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        form = QFormLayout()

        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(True)
        self._load_printers(config.printer_name)
        form.addRow("打印机：", self.printer_combo)

        self.scanner_mode_combo = QComboBox()
        self.scanner_mode_combo.addItem("串口模式", "serial")
        self.scanner_mode_combo.addItem("HID 键盘兼容模式", "hid")
        self.scanner_mode_combo.setCurrentIndex(
            max(0, self.scanner_mode_combo.findData(config.scanner_mode))
        )
        form.addRow("扫码枪模式：", self.scanner_mode_combo)

        port_row = QHBoxLayout()
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.setEditable(True)
        self._load_serial_ports(config.serial_port)
        refresh_ports_button = QPushButton("刷新串口")
        refresh_ports_button.clicked.connect(
            lambda: self._load_serial_ports(
                self.serial_port_combo.currentText().strip()
            )
        )
        port_row.addWidget(self.serial_port_combo, 1)
        port_row.addWidget(refresh_ports_button)
        form.addRow("串口：", port_row)

        self.baudrate_combo = QComboBox()
        self.baudrate_combo.setEditable(True)
        for baudrate in (9600, 19200, 38400, 57600, 115200):
            self.baudrate_combo.addItem(str(baudrate), baudrate)
        baudrate_index = self.baudrate_combo.findData(config.serial_baudrate)
        if baudrate_index < 0:
            self.baudrate_combo.addItem(
                str(config.serial_baudrate), config.serial_baudrate
            )
            baudrate_index = self.baudrate_combo.count() - 1
        self.baudrate_combo.setCurrentIndex(baudrate_index)
        form.addRow("波特率：", self.baudrate_combo)
        device_layout.addLayout(form)

        note = QLabel(
            "HID 模式可在程序内无输入框焦点时扫码，Windows 会默认切换英文布局。\n"
            "新大陆 NLS-OY20-RF 串口模式默认 9600/8/N/1/无流控，"
            "条码须以回车或换行结束。"
        )
        note.setWordWrap(True)
        device_layout.addWidget(note)
        device_layout.addStretch(1)
        tabs.addTab(device_page, "设备")

        mii_page = QWidget()
        mii_layout = QVBoxLayout(mii_page)
        mii_form = QFormLayout()
        self.mii_enabled_check = QCheckBox("启用整箱 MII 报产")
        self.mii_enabled_check.setChecked(config.mii_enabled)
        mii_form.addRow("MII开关：", self.mii_enabled_check)
        self.mii_base_url_edit = self._mii_field(
            mii_form, "MII地址：", config.mii_base_url
        )
        self.mii_transaction_edit = self._mii_field(
            mii_form, "Transaction：", config.mii_transaction
        )
        self.mii_output_edit = self._mii_field(
            mii_form, "OutputParameter：", config.mii_output_parameter
        )
        self.mii_login_edit = self._mii_field(
            mii_form, "MII账号：", config.mii_login_name
        )
        self.mii_password_edit = self._mii_field(
            mii_form,
            "MII密码：",
            config.mii_login_password,
            password=True,
        )
        self.mii_plant_edit = self._mii_field(
            mii_form, "Plant：", config.mii_plant
        )
        self.mii_user_edit = self._mii_field(
            mii_form, "UserId：", config.mii_user_id
        )
        self.mii_customer_edit = self._mii_field(
            mii_form, "CustomerCode：", config.mii_customer_code
        )
        self.mii_version_edit = self._mii_field(
            mii_form, "ProductionVersion：", config.mii_production_version
        )
        self.mii_shift_edit = self._mii_field(
            mii_form, "ProductionShift：", config.mii_production_shift
        )
        self.mii_workcenter_edit = self._mii_field(
            mii_form, "Workcenter：", config.mii_workcenter
        )
        self.mii_packaging_edit = self._mii_field(
            mii_form, "PackagingMaterial：", config.mii_packaging_material
        )
        self.mii_information_edit = self._mii_field(
            mii_form, "Information：", config.mii_information
        )
        self.mii_reverse_edit = self._mii_field(
            mii_form, "ProduceReverse：", config.mii_produce_reverse
        )
        self.mii_content_type_edit = self._mii_field(
            mii_form, "content-type：", config.mii_content_type
        )
        mii_layout.addLayout(mii_form)
        dynamic_note = QLabel(
            "动态参数无需手工配置：PartNumber=物料Excel C列，"
            "Quantity=当前箱数量，ProductionDate=报产时间，HUCode请求时留空。\n"
            "Information留空时自动使用本地内部追溯单号。密码保存在本机 config.json。"
        )
        dynamic_note.setWordWrap(True)
        mii_layout.addWidget(dynamic_note)
        mii_layout.addStretch(1)
        tabs.addTab(mii_page, "MII接口")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "保存并应用"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _mii_field(
        form: QFormLayout,
        label: str,
        value: str,
        *,
        password: bool = False,
    ) -> QLineEdit:
        editor = QLineEdit(str(value or ""))
        if password:
            editor.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(label, editor)
        return editor

    def _load_printers(self, selected: str) -> None:
        self.printer_combo.clear()
        self.printer_combo.addItem("系统默认打印机", "")
        for printer_name in _windows_printer_names():
            self.printer_combo.addItem(printer_name, printer_name)
        index = self.printer_combo.findData(selected)
        if selected and index < 0:
            self.printer_combo.addItem(selected, selected)
            index = self.printer_combo.count() - 1
        self.printer_combo.setCurrentIndex(max(0, index))

    def _load_serial_ports(self, selected: str) -> None:
        self.serial_port_combo.clear()
        ports = available_serial_ports()
        for port in ports:
            self.serial_port_combo.addItem(port)
        if selected and selected not in ports:
            self.serial_port_combo.addItem(selected)
        if selected:
            self.serial_port_combo.setCurrentText(selected)

    def _validate_and_accept(self) -> None:
        try:
            if int(self.baudrate_combo.currentText()) <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "设置错误", "波特率必须是大于 0 的整数")
            return
        if self.scanner_mode_combo.currentData() == "serial":
            if not self.serial_port_combo.currentText().strip():
                QMessageBox.warning(self, "设置错误", "串口模式必须选择 COM 端口")
                return
        if self.mii_enabled_check.isChecked():
            address = self.mii_base_url_edit.text().strip()
            parsed_address = urlparse(address)
            if (
                parsed_address.scheme not in {"http", "https"}
                or not parsed_address.netloc
                or parsed_address.hostname in {"http", "https"}
            ):
                QMessageBox.warning(
                    self,
                    "MII设置错误",
                    "MII地址必须以 http:// 或 https:// 开头",
                )
                return
            required_editors = {
                "Transaction": self.mii_transaction_edit,
                "OutputParameter": self.mii_output_edit,
                "MII账号": self.mii_login_edit,
                "MII密码": self.mii_password_edit,
                "Plant": self.mii_plant_edit,
                "UserId": self.mii_user_edit,
                "Workcenter": self.mii_workcenter_edit,
                "PackagingMaterial": self.mii_packaging_edit,
                "ProductionVersion": self.mii_version_edit,
                "ProduceReverse": self.mii_reverse_edit,
                "content-type": self.mii_content_type_edit,
            }
            missing = [
                name
                for name, editor in required_editors.items()
                if not editor.text().strip()
            ]
            if missing:
                QMessageBox.warning(
                    self,
                    "MII设置错误",
                    f"启用MII前请填写：{', '.join(missing)}",
                )
                return
        self.accept()

    def values(self) -> dict[str, object]:
        printer_name = self.printer_combo.currentData()
        if printer_name is None:
            printer_name = self.printer_combo.currentText().strip()
        return {
            "printer_name": str(printer_name or "").strip(),
            "scanner_mode": str(self.scanner_mode_combo.currentData()),
            "serial_port": self.serial_port_combo.currentText().strip(),
            "serial_baudrate": int(self.baudrate_combo.currentText()),
            "hid_force_english": True,
            "hid_capture_without_input_focus": True,
            "mii_enabled": self.mii_enabled_check.isChecked(),
            "mii_base_url": self.mii_base_url_edit.text().strip(),
            "mii_transaction": self.mii_transaction_edit.text().strip(),
            "mii_output_parameter": self.mii_output_edit.text().strip(),
            "mii_login_name": self.mii_login_edit.text().strip(),
            "mii_login_password": self.mii_password_edit.text(),
            "mii_plant": self.mii_plant_edit.text().strip(),
            "mii_user_id": self.mii_user_edit.text().strip(),
            "mii_customer_code": self.mii_customer_edit.text().strip(),
            "mii_production_version": self.mii_version_edit.text().strip(),
            "mii_production_shift": self.mii_shift_edit.text().strip(),
            "mii_workcenter": self.mii_workcenter_edit.text().strip(),
            "mii_packaging_material": self.mii_packaging_edit.text().strip(),
            "mii_information": self.mii_information_edit.text().strip(),
            "mii_produce_reverse": self.mii_reverse_edit.text().strip(),
            "mii_content_type": self.mii_content_type_edit.text().strip(),
        }


def _windows_printer_names() -> list[str]:
    if platform.system() != "Windows":
        return []
    try:
        import win32print

        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return sorted(
            {
                str(item[2])
                for item in win32print.EnumPrinters(flags)
                if len(item) > 2 and item[2]
            }
        )
    except Exception:
        return []


class HistoryDialog(QDialog):
    def __init__(self, service: ScannerService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("历史记录查询")
        self.resize(1100, 650)
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.query_type = QComboBox()
        self.query_type.addItems(
            ["完整条码", "HU号 / S码", "内部追溯单号", "日期"]
        )
        self.query_text = QLineEdit()
        self.query_text.setPlaceholderText("日期格式：YYYY-MM-DD")
        search_button = QPushButton("查询")
        search_button.clicked.connect(self._search)
        reprint_button = QPushButton("补打所选下线单")
        reprint_button.clicked.connect(self._reprint)
        open_pdf_button = QPushButton("打开PDF")
        open_pdf_button.clicked.connect(self._open_pdf)
        controls.addWidget(self.query_type)
        controls.addWidget(self.query_text, 1)
        controls.addWidget(search_button)
        controls.addWidget(open_pdf_button)
        controls.addWidget(reprint_button)
        root.addLayout(controls)

        self.table = QTableWidget(0, 14)
        self.table.setHorizontalHeaderLabels(
            [
                "内部追溯单号",
                "HU号",
                "S码",
                "箱号",
                "物料号",
                "物料名称",
                "完整条码",
                "顺序",
                "扫码时间",
                "结果",
                "记录状态",
                "作废原因",
                "作废时间",
                "已打印",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        root.addWidget(self.table)

    def _search(self) -> None:
        value = self.query_text.text().strip()
        if not value:
            return
        selected = self.query_type.currentText()
        if selected == "完整条码":
            rows = self.service.database.history_by_barcode(value)
        elif selected == "HU号 / S码":
            rows = self.service.database.history_by_hu(value)
        elif selected == "内部追溯单号":
            rows = self.service.database.history_by_order(value)
        else:
            try:
                date.fromisoformat(value)
            except ValueError:
                QMessageBox.warning(self, "日期错误", "请输入 YYYY-MM-DD")
                return
            rows = self.service.database.history_by_date(value)
        self._populate(rows)

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            is_voided = bool(row.get("is_voided", 0))
            values = [
                row["offline_order_no"],
                row.get("mii_hu_code", ""),
                row.get("mii_s_code", ""),
                row["box_no"],
                row["material_code"],
                row["material_name"],
                row["barcode"],
                row["scan_index"],
                row["scan_time"],
                row["result"],
                "已作废/重置" if is_voided else "有效",
                row.get("void_reason", "") if is_voided else "",
                row.get("voided_at", "") or "",
                "是" if row["printed"] else "否",
            ]
            for column, value in enumerate(values):
                self.table.setItem(
                    row_index, column, QTableWidgetItem(str(value))
                )

    def _reprint(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "补打", "请先选择一条记录")
            return
        order_no = self.table.item(row, 0).text()
        result = self.service.reprint(order_no)
        if result.success:
            QMessageBox.information(self, "补打", "补打命令已提交")
        else:
            QMessageBox.warning(self, "补打失败", result.message)

    def _open_pdf(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "打开PDF", "请先选择一条记录")
            return
        order_no = self.table.item(row, 0).text()
        order = self.service.database.get_order(order_no)
        pdf_path = Path(order["pdf_path"])
        if not pdf_path.is_file():
            QMessageBox.warning(self, "打开PDF", "该下线单没有可用PDF")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path.resolve())))


class MaterialDialog(QDialog):
    def __init__(self, service: ScannerService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("物料配置查看")
        self.resize(1000, 620)
        root = QVBoxLayout(self)

        actions = QHBoxLayout()
        description = QLabel(
            "物料数据来源：EHX物料号匹配.xlsx（D列为空时使用全局默认数量）"
        )
        description.setFont(QFont("Microsoft YaHei", 14))
        import_button = QPushButton("重新导入物料")
        import_button.clicked.connect(self._import_materials)
        actions.addWidget(description)
        actions.addStretch()
        actions.addWidget(import_button)
        root.addLayout(actions)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["物料条码前缀", "物料名称", "客户物料号/SAP物料号", "每箱数量"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        root.addWidget(self.table)
        self._refresh()

    def _refresh(self) -> None:
        materials = self.service.materials.reload()
        self.table.setRowCount(len(materials))
        for row_index, material in enumerate(materials):
            values = [
                material.material_code,
                material.material_name,
                material.customer_material_code,
                material.box_scan_count,
            ]
            for column, value in enumerate(values):
                self.table.setItem(
                    row_index, column, QTableWidgetItem(str(value))
                )

    def _import_materials(self) -> None:
        try:
            result = self.service.materials.import_excel()
            self._refresh()
        except Exception as exc:
            QMessageBox.warning(self, "物料导入失败", str(exc))
            return
        QMessageBox.information(
            self,
            "物料导入完成",
            (
                f"新增：{result.added} 条\n"
                f"更新：{result.updated} 条\n"
                f"禁用：{result.disabled} 条"
            ),
        )


def build_service(config_path: str | Path = "config.json") -> ScannerService:
    config_file = Path(config_path).expanduser().resolve()
    base_dir = config_file.parent
    config = load_config(config_file)

    def resolve_config_path(value: str) -> str:
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else (base_dir / path).resolve())

    config = replace(
        config,
        template_path=resolve_config_path(config.template_path),
        output_pdf_dir=resolve_config_path(config.output_pdf_dir),
        database_path=resolve_config_path(config.database_path),
        material_excel_path=resolve_config_path(config.material_excel_path),
        barcode_output_dir=resolve_config_path(config.barcode_output_dir),
    )
    database = Database(
        config.database_path,
        default_box_scan_count=config.box_scan_count,
    )
    materials = MaterialRepository(
        database,
        config.material_excel_path,
        default_box_scan_count=config.box_scan_count,
    )
    service = ScannerService(config, database, materials)
    service.config_path = config_file
    return service
