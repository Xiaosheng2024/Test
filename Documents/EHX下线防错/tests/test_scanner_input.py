from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

from ehx_guard.scanner_input import HidScanFilter, SerialScanner


class ScannerInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_hid_receives_barcode_when_button_has_focus(self) -> None:
        scanner = HidScanFilter()
        scanner.enabled = True
        received: list[str] = []
        scanner.barcode_received.connect(received.append)
        self.application.installEventFilter(scanner)
        button = QPushButton("非扫码输入框")
        button.show()
        button.setFocus()

        keys = [
            (Qt.Key.Key_5, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_6, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_6, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_4, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_6, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_3, Qt.KeyboardModifier.ShiftModifier),
            (Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier),
        ]
        for key, modifiers in keys:
            self.application.sendEvent(
                button,
                QKeyEvent(QEvent.Type.KeyPress, key, modifiers),
            )
        self.application.sendEvent(
            button,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        self.application.processEvents()

        self.assertEqual(["5664620FA2#01"], received)
        self.application.removeEventFilter(scanner)
        button.close()

    def test_serial_fragments_and_crlf_emit_once_per_barcode(self) -> None:
        scanner = SerialScanner()
        received: list[str] = []
        scanner.barcode_received.connect(received.append)
        scanner.feed_bytes(b"5664620FA2#01#20260710")
        scanner.feed_bytes(b"#0060\r\nNEXT-001\n")
        self.application.processEvents()
        self.assertEqual(
            ["5664620FA2#01#20260710#0060", "NEXT-001"],
            received,
        )

    def test_serial_accepts_cr_lf_crlf_sticky_and_split_packets(self) -> None:
        cases = [
            ([b"ABC123\r"], ["ABC123"]),
            ([b"ABC123\n"], ["ABC123"]),
            ([b"ABC123\r\n"], ["ABC123"]),
            ([b"ABC123\rDEF456\r"], ["ABC123", "DEF456"]),
            ([b"ABC", b"123\r"], ["ABC123"]),
            ([b"  ABC123  \r\n\r"], ["ABC123"]),
        ]
        for chunks, expected in cases:
            with self.subTest(chunks=chunks):
                scanner = SerialScanner()
                received: list[str] = []
                scanner.barcode_received.connect(received.append)
                for chunk in chunks:
                    scanner.feed_bytes(chunk)
                self.application.processEvents()
                self.assertEqual(expected, received)


if __name__ == "__main__":
    unittest.main()
