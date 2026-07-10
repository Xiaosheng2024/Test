from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from ehx_guard.mii_client import MiiClient, _mask_password, _parse_response, _runner_url


def _make_client(**overrides) -> MiiClient:
    kwargs = dict(
        enabled=True,
        base_url="https://mii.example:50001/XMII/",
        login_name="zhangto",
        login_password="secret",
        plant="1680",
        user_id="zhangto",
        workcenter="WC00311",
        packaging_material="GENERIC_PACN",
    )
    kwargs.update(overrides)
    return MiiClient(**kwargs)


class MiiRunnerUrlTest(unittest.TestCase):
    def test_appends_runner_when_missing(self) -> None:
        self.assertEqual(
            "https://mii.example:50001/XMII/Runner",
            _runner_url("https://mii.example:50001/XMII/"),
        )

    def test_keeps_existing_runner_and_strips_query(self) -> None:
        self.assertEqual(
            "https://mii.example:50001/XMII/Runner",
            _runner_url("https://mii.example:50001/XMII/Runner?Transaction=x"),
        )

    def test_empty_base_url_returns_empty(self) -> None:
        self.assertEqual("", _runner_url(""))
        self.assertEqual("", _runner_url("   "))


class MiiMissingFieldsTest(unittest.TestCase):
    def test_disabled_client_short_circuits_without_validation(self) -> None:
        client = _make_client(enabled=False, login_name="")
        result = client.upload_offline_order(
            {"customer_material_code": "566462001FA2", "required_count": 1}
        )
        self.assertFalse(result.success)
        self.assertEqual("MII disabled", result.message)

    def test_missing_required_config_field_blocks_request(self) -> None:
        client = _make_client(plant="")
        with patch("ehx_guard.mii_client.urllib.request.urlopen") as urlopen:
            result = client.upload_offline_order(
                {"customer_material_code": "566462001FA2", "required_count": 1}
            )
        urlopen.assert_not_called()
        self.assertFalse(result.success)
        self.assertIn("mii_plant", result.message)

    def test_missing_order_data_blocks_request(self) -> None:
        client = _make_client()
        with patch("ehx_guard.mii_client.urllib.request.urlopen") as urlopen:
            result = client.upload_offline_order({"customer_material_code": ""})
        urlopen.assert_not_called()
        self.assertFalse(result.success)
        self.assertIn("PartNumber/customer_material_code", result.message)


class MiiBuildUrlTest(unittest.TestCase):
    def test_url_carries_config_and_order_fields(self) -> None:
        client = _make_client(information="TEST")
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

    def test_information_mode_box_no_falls_back_to_box_no(self) -> None:
        client = _make_client(information_mode="box_no")
        query = parse_qs(
            urlsplit(
                client._build_url(
                    {
                        "offline_order_no": "INTERNAL-1",
                        "box_no": "BOX-7",
                        "customer_material_code": "566462001FA2",
                        "required_count": 1,
                    }
                )
            ).query
        )
        self.assertEqual(["BOX-7"], query["Information"])


class MiiUploadOfflineOrderTest(unittest.TestCase):
    def test_success_response_parses_status_and_codes(self) -> None:
        client = _make_client()
        response = MagicMock()
        response.read.return_value = (
            b"<Status>PRODUCED</Status><HUCode>1368123456965</HUCode>"
        )
        response.__enter__.return_value = response
        with patch(
            "ehx_guard.mii_client.urllib.request.urlopen", return_value=response
        ):
            result = client.upload_offline_order(
                {"customer_material_code": "566462001FA2", "required_count": 1}
            )
        self.assertTrue(result.success)
        self.assertEqual("PRODUCED", result.status)
        self.assertEqual("1368123456965", result.hu_code)
        self.assertEqual("S123456965", result.s_code)
        self.assertNotIn("secret", result.request_url)

    def test_network_error_is_reported_without_raising(self) -> None:
        client = _make_client()
        with patch(
            "ehx_guard.mii_client.urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            result = client.upload_offline_order(
                {"customer_material_code": "566462001FA2", "required_count": 1}
            )
        self.assertFalse(result.success)
        self.assertIn("MII请求失败", result.message)

    def test_short_hu_code_is_treated_as_failure(self) -> None:
        client = _make_client()
        response = MagicMock()
        response.read.return_value = (
            b"<Status>PRODUCED</Status><HUCode>1234</HUCode>"
        )
        response.__enter__.return_value = response
        with patch(
            "ehx_guard.mii_client.urllib.request.urlopen", return_value=response
        ):
            result = client.upload_offline_order(
                {"customer_material_code": "566462001FA2", "required_count": 1}
            )
        self.assertFalse(result.success)
        self.assertEqual("", result.s_code)
        self.assertIn("HUCode不足9位", result.message)

    def test_missing_produced_status_is_treated_as_failure(self) -> None:
        client = _make_client()
        response = MagicMock()
        response.read.return_value = (
            b"<Status>ERROR</Status><Message>Plant invalid</Message>"
        )
        response.__enter__.return_value = response
        with patch(
            "ehx_guard.mii_client.urllib.request.urlopen", return_value=response
        ):
            result = client.upload_offline_order(
                {"customer_material_code": "566462001FA2", "required_count": 1}
            )
        self.assertFalse(result.success)
        self.assertEqual("Plant invalid", result.message)


class MiiParseResponseFallbackTest(unittest.TestCase):
    def test_xml_document_without_flat_tags_is_parsed(self) -> None:
        raw = (
            '<?xml version="1.0"?>'
            "<Rowset><Row><Status>PRODUCED</Status>"
            "<HUCode>9998887776665</HUCode></Row></Rowset>"
        )
        parsed = _parse_response(raw)
        self.assertTrue(parsed.success)
        self.assertEqual("S887776665", parsed.s_code)

    def test_unparseable_response_reports_failure(self) -> None:
        parsed = _parse_response("not xml at all")
        self.assertFalse(parsed.success)
        self.assertEqual("MII未返回PRODUCED/HUCode", parsed.message)


class MiiMaskPasswordTest(unittest.TestCase):
    def test_password_is_masked_in_logged_url(self) -> None:
        url = (
            "https://mii.example/XMII/Runner?"
            "XacuteLoginPassword=secret&Plant=1680"
        )
        masked = _mask_password(url)
        self.assertNotIn("secret", masked)
        self.assertIn("XacuteLoginPassword=***", masked)


if __name__ == "__main__":
    unittest.main()
