"""HID 键盘扫码和串口扫码输入适配。"""

from __future__ import annotations

import ctypes
import logging
import platform
import time

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication


class HidScanFilter(QObject):
    """在程序内不依赖输入框焦点接收 HID 扫码。"""

    barcode_received = Signal(str)
    preview_changed = Signal(str)

    def __init__(self, timeout_seconds: float = 0.5) -> None:
        super().__init__()
        self.enabled = False
        self.paused = False
        self.timeout_seconds = timeout_seconds
        self._buffer = ""
        self._last_key_at = 0.0

    def clear(self) -> None:
        self._buffer = ""
        self._last_key_at = 0.0
        self.preview_changed.emit("")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            not self.enabled
            or self.paused
            or event.type() != QEvent.Type.KeyPress
            or QApplication.activeModalWidget() is not None
        ):
            return False

        modifiers = event.modifiers()
        if modifiers & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return False

        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            barcode = self._buffer.strip()
            self.clear()
            if barcode:
                self.barcode_received.emit(barcode)
                return True
            return False
        if key == Qt.Key.Key_Backspace and self._buffer:
            self._buffer = self._buffer[:-1]
            self.preview_changed.emit(self._buffer)
            return True

        character = _key_to_ascii(key, modifiers)
        if not character:
            return False
        now = time.monotonic()
        if self._last_key_at and now - self._last_key_at > self.timeout_seconds:
            self._buffer = ""
        self._last_key_at = now
        self._buffer += character
        self.preview_changed.emit(self._buffer)
        return True


def _key_to_ascii(key: int, modifiers: Qt.KeyboardModifier) -> str:
    """直接按键码转扫码 ASCII，不依赖中文输入法文本。"""

    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(ord("A") + key - Qt.Key.Key_A)
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        if (
            key == Qt.Key.Key_3
            and modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            return "#"
        return chr(ord("0") + key - Qt.Key.Key_0)
    return {
        Qt.Key.Key_NumberSign: "#",
        Qt.Key.Key_Minus: "-",
        Qt.Key.Key_Underscore: "_",
        Qt.Key.Key_Period: ".",
        Qt.Key.Key_Slash: "/",
    }.get(key, "")


class SerialScanner(QObject):
    """非阻塞读取串口，按 CR/LF 拆分完整条码。"""

    barcode_received = Signal(str)
    connection_error = Signal(str)

    def __init__(self, logger: logging.Logger | None = None) -> None:
        super().__init__()
        self.logger = logger or logging.getLogger("ehx_guard.serial_scanner")
        self._serial = None
        self._buffer = bytearray()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)

    @property
    def connected(self) -> bool:
        return bool(self._serial and getattr(self._serial, "is_open", False))

    def start(self, port: str, baudrate: int) -> None:
        self.stop()
        if not port:
            raise ValueError(
                "串口模式必须选择 COM 端口；"
                "如设备管理器没有COM口，请检查USB转串口驱动"
            )
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("未安装 pyserial，无法使用串口扫码枪") from exc
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as exc:
            self._serial = None
            raise RuntimeError(
                f"串口 {port} 不存在或打开失败：{exc}。"
                "请检查COM口配置、端口是否被占用和USB转串口驱动"
            ) from exc
        self._buffer.clear()
        self._timer.start()
        self.logger.info("串口扫码枪已连接 port=%s baudrate=%s", port, baudrate)

    def stop(self) -> None:
        self._timer.stop()
        serial_device = self._serial
        self._serial = None
        self._buffer.clear()
        if serial_device is not None:
            try:
                serial_device.close()
            except Exception:
                self.logger.exception("关闭串口扫码枪失败")

    def feed_bytes(self, data: bytes) -> None:
        """累积串口分片；保留为无硬件定向测试入口。"""

        self._buffer.extend(data.replace(b"\r", b"\n"))
        while b"\n" in self._buffer:
            line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            barcode = line.decode("ascii", errors="ignore").strip()
            if barcode:
                self.barcode_received.emit(barcode)

    def _poll(self) -> None:
        if not self.connected:
            return
        try:
            waiting = int(getattr(self._serial, "in_waiting", 0))
            if waiting:
                self.feed_bytes(self._serial.read(waiting))
        except Exception as exc:
            self.logger.exception("串口扫码读取失败")
            self.stop()
            self.connection_error.emit(f"串口扫码枪连接中断：{exc}")


def available_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [item.device for item in list_ports.comports()]


def force_windows_english_layout() -> bool:
    """将当前 Windows GUI 线程切换到英文键盘布局。"""

    if platform.system() != "Windows":
        return False
    try:
        user32 = ctypes.windll.user32
        layout = user32.LoadKeyboardLayoutW("00000409", 1)
        return bool(layout and user32.ActivateKeyboardLayout(layout, 0))
    except Exception:
        logging.getLogger("ehx_guard.hid_scanner").exception(
            "Windows 英文键盘布局切换失败"
        )
        return False
