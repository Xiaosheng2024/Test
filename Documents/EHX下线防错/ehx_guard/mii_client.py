"""MII 报产客户端。"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class MiiUploadResult:
    success: bool
    status: str = ""
    hu_code: str = ""
    s_code: str = ""
    message: str = ""
    raw_response: str = ""
    request_url: str = ""


class MiiClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "",
        token: str = "",
        transaction: str = (
            "SC_AUTOMATION/API/PRODUCTION/V1/TRANSACTION/PRODUCTION_API"
        ),
        output_parameter: str = "ResultXML",
        login_name: str = "",
        login_password: str = "",
        plant: str = "",
        user_id: str = "",
        customer_code: str = "",
        production_version: str = "0001",
        production_shift: str = "",
        workcenter: str = "",
        packaging_material: str = "",
        information_mode: str = "offline_order_no",
        information: str = "",
        produce_reverse: str = "P",
        content_type: str = "text/xml",
        timeout_seconds: int = 10,
        logger: logging.Logger | None = None,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url
        self.token = token
        self.transaction = transaction
        self.output_parameter = output_parameter
        self.login_name = login_name
        self.login_password = login_password
        self.plant = plant
        self.user_id = user_id
        self.customer_code = customer_code
        self.production_version = production_version or "0001"
        self.production_shift = production_shift
        self.workcenter = workcenter
        self.packaging_material = packaging_material
        self.information_mode = information_mode or "offline_order_no"
        self.information = information
        self.produce_reverse = produce_reverse or "P"
        self.content_type = content_type or "text/xml"
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.logger = logger or logging.getLogger("ehx_guard.mii")

    def upload_offline_order(
        self, order_data: Mapping[str, Any]
    ) -> MiiUploadResult:
        order_no = order_data.get("offline_order_no", "")
        if not self.enabled:
            self.logger.info("MII disabled，跳过上传 order=%s", order_no)
            return MiiUploadResult(False, message="MII disabled")

        missing = self._missing_fields(order_data)
        if missing:
            message = f"MII配置缺失：{', '.join(missing)}"
            self.logger.error("%s order=%s", message, order_no)
            return MiiUploadResult(False, message=message)

        request_url = self._build_url(order_data)
        safe_url = _mask_password(request_url)
        self.logger.info(
            "MII报产开始 order=%s part=%s qty=%s url=%s",
            order_no,
            order_data.get("customer_material_code", ""),
            order_data.get("required_count", ""),
            safe_url,
        )
        try:
            with urllib.request.urlopen(
                request_url, timeout=self.timeout_seconds
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            message = f"MII请求失败：{exc}"
            self.logger.exception(
                "MII报产失败 order=%s url=%s", order_no, safe_url
            )
            return MiiUploadResult(
                False, message=message, request_url=safe_url
            )

        parsed = _parse_response(raw)
        if parsed.success:
            self.logger.info(
                "MII报产成功 order=%s status=%s hu=%s s=%s",
                order_no,
                parsed.status,
                parsed.hu_code,
                parsed.s_code,
            )
        else:
            self.logger.error(
                "MII报产返回失败 order=%s status=%s message=%s",
                order_no,
                parsed.status,
                parsed.message,
            )
        return MiiUploadResult(
            parsed.success,
            status=parsed.status,
            hu_code=parsed.hu_code,
            s_code=parsed.s_code,
            message=parsed.message,
            raw_response=raw,
            request_url=safe_url,
        )

    def _missing_fields(self, order_data: Mapping[str, Any]) -> list[str]:
        required = {
            "mii_base_url": self.base_url,
            "mii_transaction": self.transaction,
            "mii_output_parameter": self.output_parameter,
            "mii_login_name": self.login_name,
            "mii_login_password": self.login_password,
            "mii_plant": self.plant,
            "mii_user_id": self.user_id,
            "mii_workcenter": self.workcenter,
            "mii_packaging_material": self.packaging_material,
            "mii_production_version": self.production_version,
            "mii_produce_reverse": self.produce_reverse,
            "mii_content_type": self.content_type,
            "PartNumber/customer_material_code": order_data.get(
                "customer_material_code", ""
            ),
            "Quantity/required_count": order_data.get("required_count", ""),
        }
        return [name for name, value in required.items() if not str(value).strip()]

    def _build_url(self, order_data: Mapping[str, Any]) -> str:
        endpoint = _runner_url(self.base_url)
        production_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        information = self.information or (
            str(order_data.get("box_no", ""))
            if self.information_mode == "box_no"
            else str(order_data.get("offline_order_no", ""))
        )
        query = {
            "Transaction": self.transaction,
            "XacuteLoginName": self.login_name,
            "XacuteLoginPassword": self.login_password,
            "OutputParameter": self.output_parameter,
            "Plant": self.plant,
            "PartNumber": str(order_data.get("customer_material_code", "")),
            "CustomerCode": self.customer_code,
            "UserId": self.user_id,
            "HUCode": "",
            "Quantity": str(order_data.get("required_count", "")),
            "ProductionVersion": self.production_version,
            "ProductionShift": self.production_shift,
            "Workcenter": self.workcenter,
            "ProductionDate": production_time,
            "ProduceReverse": self.produce_reverse,
            "PackagingMaterial": self.packaging_material,
            "Information": information,
            "content-type": self.content_type,
        }
        return f"{endpoint}?{urllib.parse.urlencode(query)}"


def _runner_url(base_url: str) -> str:
    base = base_url.strip()
    if not base:
        return ""
    if "Runner" in base:
        return base.split("?", 1)[0]
    return urllib.parse.urljoin(base.rstrip("/") + "/", "Runner")


def _parse_response(raw: str) -> MiiUploadResult:
    status = _find_tag_value(raw, "Status")
    hu_code = _find_tag_value(raw, "HUCode")
    message = _find_tag_value(raw, "Message")
    if not status or not hu_code:
        status, hu_code, message = _parse_xml_fallback(
            raw, status, hu_code, message
        )
    s_code = build_s_code(hu_code)
    success = status.upper() == "PRODUCED" and bool(s_code)
    if success:
        return MiiUploadResult(
            True,
            status=status,
            hu_code=hu_code,
            s_code=s_code,
            message=message or "PRODUCED",
        )
    return MiiUploadResult(
        False,
        status=status,
        hu_code=hu_code,
        s_code=s_code,
        message=(
            message
            or ("MII返回的HUCode不足9位" if hu_code else "MII未返回PRODUCED/HUCode")
        ),
    )


def build_s_code(hu_code: str) -> str:
    """生产标签 S 码：字面 S + MII HUCode 后 9 位。"""

    hu = str(hu_code or "").strip()
    return f"S{hu[-9:]}" if len(hu) >= 9 else ""


def _find_tag_value(raw: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", raw, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_xml_fallback(
    raw: str, status: str, hu_code: str, message: str
) -> tuple[str, str, str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return status, hu_code, message
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1].lower()
        text = (element.text or "").strip()
        if not text:
            continue
        if name == "status" and not status:
            status = text
        elif name == "hucode" and not hu_code:
            hu_code = text
        elif name == "message" and not message:
            message = text
    return status, hu_code, message


def _mask_password(url: str) -> str:
    return re.sub(
        r"(XacuteLoginPassword=)[^&]*",
        r"\1***",
        url,
        flags=re.IGNORECASE,
    )
