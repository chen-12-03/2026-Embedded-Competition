"""
共享 NFC 硬件接口
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


PN532_ACK_FRAME = b"\x00\x00\xFF\x00\xFF\x00"
PN532_HSU_WAKEUP = b"\x55\x55\x00\x00\x00"
PN532_I2C_READY = 0x01
PN532_SPI_READY_MASK = 0x01
PN532_MIFARE_ISO14443A = 0x00
MIFARE_CMD_AUTH_A = 0x60
MIFARE_CMD_READ = 0x30
MATERIAL_ID_PATTERNS = (
    re.compile(r'"material_id"\s*:\s*"([^"]+)"'),
    re.compile(r"MAT[0-9A-Za-z_-]{2,}"),
    re.compile(r"\bMAT[0-9A-Za-z_-]{2,}\b"),
    re.compile(r"\b[A-Z]{2,}[0-9][A-Z0-9_-]{1,31}\b"),
)


@dataclass
class NFCReadResult:
    """NFC 单次读卡结果。"""

    success: bool
    material_id: Optional[str] = None
    text: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "material_id": self.material_id,
            "text": self.text,
            "error": self.error,
            "raw": self.raw,
        }


class BaseNFCReader:
    """NFC 读卡器基础接口。"""

    def read_result(self) -> NFCReadResult:
        raise NotImplementedError

    def read_once(self) -> NFCReadResult:
        return self.read_result()

    def read(self) -> Dict:
        return self.read_result().to_dict()


class MockNFCReader(BaseNFCReader):
    """
    模拟 NFC 读卡器。

    兼容两种用法：
    1. 基础测试脚本循环读固定 ID
    2. 主系统通过 `last_read` 注入下一次读卡结果
    """

    def __init__(self, material_ids: Optional[List[str]] = None):
        self.material_ids = material_ids or ["MAT001", "MAT002", "MAT003"]
        self.index = 0
        self.last_read: Optional[Dict] = None

    def set_next_result(self, payload: Dict) -> None:
        self.last_read = dict(payload)

    def write(self, material_id: str) -> bool:
        if material_id not in self.material_ids:
            self.material_ids.append(material_id)
        return True

    def read_result(self) -> NFCReadResult:
        if self.last_read is not None:
            payload = dict(self.last_read)
            self.last_read = None
            return NFCReadResult(
                success=bool(payload.get("success", False)),
                material_id=payload.get("material_id"),
                text=payload["text"] if "text" in payload else payload.get("material_id"),
                error=payload.get("error"),
                raw=payload,
            )

        material_id = self.material_ids[self.index % len(self.material_ids)]
        self.index += 1
        return NFCReadResult(
            success=True,
            material_id=material_id,
            text=material_id,
            raw={"mode": "mock"},
        )


class FileNFCReader(BaseNFCReader):
    """从文本文件中读取 material_id。"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def read_result(self) -> NFCReadResult:
        if not self.file_path.exists():
            return NFCReadResult(success=False, error=f"File not found: {self.file_path}")

        content = self.file_path.read_text(encoding="utf-8").strip()
        if not content:
            return NFCReadResult(success=False, error="NFC result file is empty")

        return NFCReadResult(
            success=True,
            material_id=content,
            text=content,
            raw={"mode": "file"},
        )


class CommandNFCReader(BaseNFCReader):
    """通过外部命令读取 NFC。"""

    def __init__(self, command: str, timeout: float = 3.0):
        self.command = command
        self.timeout = timeout

    def read_result(self) -> NFCReadResult:
        try:
            completed = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except Exception as exc:
            return NFCReadResult(success=False, error=str(exc))

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

        if completed.returncode != 0:
            return NFCReadResult(
                success=False,
                error=stderr or f"command exited with {completed.returncode}",
            )

        if not stdout:
            return NFCReadResult(success=False, error="command returned empty output")

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return NFCReadResult(
                success=True,
                material_id=stdout,
                text=stdout,
                raw={"mode": "command"},
            )

        return NFCReadResult(
            success=bool(payload.get("success", True)),
            material_id=payload.get("material_id"),
            text=payload["text"] if "text" in payload else payload.get("material_id"),
            error=payload.get("error"),
            raw=payload,
        )


@dataclass
class PN532PinConfig:
    """记录板端接线，便于联调和日志输出。"""

    interface: str
    sda: Optional[str] = None
    scl: Optional[str] = None
    mosi: Optional[str] = None
    miso: Optional[str] = None
    sck: Optional[str] = None
    cs: Optional[str] = None
    tx: Optional[str] = None
    rx: Optional[str] = None
    irq: Optional[str] = None
    rstpdn: Optional[str] = None
    vcc: Optional[str] = None
    gnd: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        payload: Dict[str, str] = {"interface": self.interface}
        for field_name in (
            "sda",
            "scl",
            "mosi",
            "miso",
            "sck",
            "cs",
            "tx",
            "rx",
            "irq",
            "rstpdn",
            "vcc",
            "gnd",
        ):
            value = getattr(self, field_name)
            if value:
                payload[field_name] = value
        return payload


def _coerce_pin_config(interface: str, pin_config: Optional[Any]) -> PN532PinConfig:
    if isinstance(pin_config, PN532PinConfig):
        return pin_config
    if isinstance(pin_config, dict):
        payload = dict(pin_config)
        payload.setdefault("interface", interface)
        return PN532PinConfig(**payload)
    return PN532PinConfig(interface=interface)


class BasePN532Transport:
    """PN532 总线传输抽象。"""

    interface = "unknown"

    def wait_ready(self, timeout: float) -> bool:
        raise NotImplementedError

    def write_frame(self, frame: bytes) -> None:
        raise NotImplementedError

    def read_data(self, size: int) -> bytes:
        raise NotImplementedError

    def read_full_response(self, command: int) -> Optional[bytes]:
        del command
        return None

    def describe(self) -> Dict[str, Any]:
        return {"interface": self.interface}

    def close(self) -> None:
        pass


class PN532I2CTransport(BasePN532Transport):
    """基于 Linux I2C 的 PN532 传输层。"""

    interface = "i2c"

    def __init__(self, bus_id: int = 1, address: int = 0x24):
        try:
            from smbus2 import SMBus, i2c_msg
        except ImportError as exc:  # pragma: no cover - 依赖按板端环境提供
            raise RuntimeError("pn532_i2c backend requires `smbus2` package") from exc

        self.bus_id = int(bus_id)
        self.address = int(address)
        self._bus = SMBus(self.bus_id)
        self._i2c_msg = i2c_msg
        self._status_poll_interval = 0.005
        self._post_ready_delay = 0.002
        self._write_settle_delay = 0.002
        self._startup_settle_delay = 0.1
        self._max_frame_read = 64
        time.sleep(self._startup_settle_delay)
        self._flush_status_polls()

    def _flush_status_polls(self, attempts: int = 3) -> None:
        """模仿参考实现的上电稳定等待，预先做几次状态读取。"""
        for _ in range(max(1, attempts)):
            try:
                msg = self._i2c_msg.read(self.address, 1)
                self._bus.i2c_rdwr(msg)
            except Exception:
                break
            time.sleep(self._status_poll_interval)

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.01, timeout)
        while time.monotonic() < deadline:
            msg = self._i2c_msg.read(self.address, 1)
            self._bus.i2c_rdwr(msg)
            if bytes(msg)[0] == PN532_I2C_READY:
                # Some PN532 I2C boards raise the ready flag slightly before
                # the ACK/response frame can be read out stably.
                time.sleep(self._post_ready_delay)
                return True
            time.sleep(self._status_poll_interval)
        return False

    def write_frame(self, frame: bytes) -> None:
        msg = self._i2c_msg.write(self.address, bytes(frame))
        self._bus.i2c_rdwr(msg)
        time.sleep(self._write_settle_delay)

    def read_data(self, size: int) -> bytes:
        deadline = time.monotonic() + 0.2
        last_status = None
        while time.monotonic() < deadline:
            msg = self._i2c_msg.read(self.address, size + 1)
            self._bus.i2c_rdwr(msg)
            payload = bytes(msg)
            if payload and payload[0] == PN532_I2C_READY:
                return payload[1:]
            last_status = payload[0] if payload else None
            time.sleep(self._status_poll_interval)
        raise RuntimeError(
            "PN532 I2C returned not-ready status during read"
            f" (last_status={last_status!r}, size={size})"
        )

    def read_full_response(self, command: int) -> Optional[bytes]:
        del command
        raw = self.read_data(self._max_frame_read)
        if len(raw) < 7 or raw[:3] != b"\x00\x00\xFF":
            raise RuntimeError(f"Invalid PN532 response header: {raw.hex()}")

        length = raw[3]
        length_checksum = raw[4]
        if ((length + length_checksum) & 0xFF) != 0:
            raise RuntimeError("PN532 response length checksum mismatch")
        if length in (0x00, 0xFF):
            raise RuntimeError("PN532 empty or extended frames are not supported here")

        frame_size = length + 7
        if len(raw) < frame_size:
            raise RuntimeError(
                f"PN532 I2C response shorter than expected: need {frame_size}, got {len(raw)}"
            )
        return raw[:frame_size]

    def describe(self) -> Dict[str, Any]:
        return {
            "interface": self.interface,
            "bus": self.bus_id,
            "address": hex(self.address),
        }

    def close(self) -> None:
        self._bus.close()


class PN532SPITransport(BasePN532Transport):
    """基于 Linux spidev 的 PN532 传输层。"""

    interface = "spi"

    def __init__(self, bus: int = 0, device: int = 0, speed_hz: int = 1_000_000):
        try:
            import spidev
        except ImportError as exc:  # pragma: no cover - 依赖按板端环境提供
            raise RuntimeError("pn532_spi backend requires `spidev` package") from exc

        self.bus = int(bus)
        self.device = int(device)
        self.speed_hz = int(speed_hz)
        self._spi = spidev.SpiDev()
        self._spi.open(self.bus, self.device)
        self._spi.max_speed_hz = self.speed_hz
        self._spi.mode = 0

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.01, timeout)
        while time.monotonic() < deadline:
            response = self._spi.xfer2([0x02, 0x00])
            if len(response) >= 2 and (response[1] & PN532_SPI_READY_MASK):
                return True
            time.sleep(0.01)
        return False

    def write_frame(self, frame: bytes) -> None:
        self._spi.xfer2([0x01] + list(frame))

    def read_data(self, size: int) -> bytes:
        response = self._spi.xfer2([0x03] + [0x00] * size)
        if len(response) < size + 1:
            raise RuntimeError("PN532 SPI read length is shorter than expected")
        return bytes(response[1:])

    def describe(self) -> Dict[str, Any]:
        return {
            "interface": self.interface,
            "bus": self.bus,
            "device": self.device,
            "speed_hz": self.speed_hz,
        }

    def close(self) -> None:
        self._spi.close()


class PN532UARTTransport(BasePN532Transport):
    """基于 Linux 串口的 PN532 HSU 传输层。"""

    interface = "uart"

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.1):
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - 依赖按板端环境提供
            raise RuntimeError("pn532_uart backend requires `pyserial` package") from exc

        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.01, timeout)
        while time.monotonic() < deadline:
            if self._serial.in_waiting > 0:
                return True
            time.sleep(0.01)
        return False

    def write_frame(self, frame: bytes) -> None:
        self._serial.reset_input_buffer()
        self._serial.write(PN532_HSU_WAKEUP)
        self._serial.flush()
        time.sleep(0.02)
        self._serial.write(bytes(frame))
        self._serial.flush()

    def read_data(self, size: int) -> bytes:
        payload = bytearray()
        deadline = time.monotonic() + max(0.1, self.timeout * max(1, size) * 2)
        while len(payload) < size and time.monotonic() < deadline:
            chunk = self._serial.read(size - len(payload))
            if chunk:
                payload.extend(chunk)
                continue
            time.sleep(0.005)
        if len(payload) < size:
            raise RuntimeError(
                f"PN532 UART read timeout: expected {size} bytes, got {len(payload)}"
            )
        return bytes(payload)

    def describe(self) -> Dict[str, Any]:
        return {
            "interface": self.interface,
            "port": self.port,
            "baudrate": self.baudrate,
        }

    def close(self) -> None:
        self._serial.close()


def _normalize_text_candidate(text: str) -> Optional[str]:
    if not text:
        return None

    text = text.replace("\x00", " ").replace("\xFF", " ")
    text = "".join(char if char.isprintable() or char == "\n" else " " for char in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    compact = "\n".join(line for line in lines if line)
    compact = re.sub(r"[ \t\f\v]+", " ", compact).strip()
    if not compact:
        return None

    if "\n" not in compact:
        compact = re.sub(r"^[a-z]{2,8}(?=(\{|[A-Z0-9]))", "", compact).strip()

    return compact or None


def _extract_material_id_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    for pattern in MATERIAL_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1) if match.groups() else match.group(0)

    for chunk in re.findall(r"\{[^{}]+\}", text):
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        material_id = data.get("material_id")
        if isinstance(material_id, str) and material_id.strip():
            return material_id.strip()

    tokens = [
        token.strip()
        for token in re.split(r"[^0-9A-Za-z_-]+", text)
        if token.strip()
    ]
    for token in tokens:
        if any(char.isdigit() for char in token) and len(token) >= 4:
            return token

    return None


def _iter_ndef_messages(payload: bytes):
    index = 0
    total = len(payload)
    while index < total:
        tlv_type = payload[index]
        index += 1

        if tlv_type == 0x00:
            continue
        if tlv_type == 0xFE:
            break
        if index >= total:
            break

        tlv_length = payload[index]
        index += 1
        if tlv_length == 0xFF:
            if index + 2 > total:
                break
            tlv_length = int.from_bytes(payload[index:index + 2], "big")
            index += 2

        value_end = min(index + tlv_length, total)
        value = payload[index:value_end]
        index = value_end
        if tlv_type == 0x03 and value:
            yield bytes(value)


def _decode_ndef_text_record(record_payload: bytes) -> Optional[str]:
    if not record_payload:
        return None

    status = record_payload[0]
    language_length = status & 0x3F
    if language_length >= len(record_payload):
        return None

    text_payload = record_payload[1 + language_length:]
    if not text_payload:
        return None

    encoding = "utf-16" if (status & 0x80) else "utf-8"
    try:
        decoded = text_payload.decode(encoding)
    except UnicodeDecodeError:
        return None
    return _normalize_text_candidate(decoded)


def _extract_ndef_text_from_message(message: bytes) -> Optional[str]:
    index = 0
    total = len(message)

    while index < total:
        if index + 2 > total:
            return None
        header = message[index]
        index += 1
        type_length = message[index]
        index += 1

        short_record = bool(header & 0x10)
        has_id_length = bool(header & 0x08)
        if short_record:
            if index >= total:
                return None
            payload_length = message[index]
            index += 1
        else:
            if index + 4 > total:
                return None
            payload_length = int.from_bytes(message[index:index + 4], "big")
            index += 4

        id_length = 0
        if has_id_length:
            if index >= total:
                return None
            id_length = message[index]
            index += 1

        if index + type_length + id_length + payload_length > total:
            return None

        type_bytes = bytes(message[index:index + type_length])
        index += type_length
        index += id_length
        record_payload = bytes(message[index:index + payload_length])
        index += payload_length

        tnf = header & 0x07
        if tnf == 0x01 and type_bytes == b"T":
            text = _decode_ndef_text_record(record_payload)
            if text:
                return text

        if header & 0x40:
            break

    return None


def extract_text_from_payload(payload: bytes) -> Optional[str]:
    """从 NFC 原始载荷里尽量提取人类可读文本。"""
    if not payload:
        return None

    for message in _iter_ndef_messages(payload):
        text = _extract_ndef_text_from_message(message)
        if text:
            return text

    utf8_text = _normalize_text_candidate(payload.decode("utf-8", errors="ignore"))
    if utf8_text:
        return utf8_text

    sanitized = payload.replace(b"\x00", b" ").replace(b"\xFF", b" ")
    ascii_text = "".join(chr(byte) if 32 <= byte <= 126 else " " for byte in sanitized)

    for chunk in re.findall(r"\{[^{}]+\}", ascii_text):
        text = _normalize_text_candidate(chunk)
        if text:
            return text

    segments = sorted(
        (segment for segment in re.findall(r"[ -~]{4,}", ascii_text) if segment.strip()),
        key=len,
        reverse=True,
    )
    for segment in segments:
        text = _normalize_text_candidate(segment)
        if text:
            return text

    return None


def extract_material_id_from_payload(payload: bytes) -> Optional[str]:
    """从 NFC 原始载荷里尽量提取 `material_id`。"""
    if not payload:
        return None

    text = extract_text_from_payload(payload)
    material_id = _extract_material_id_from_text(text)
    if material_id:
        return material_id

    sanitized = payload.replace(b"\x00", b" ").replace(b"\xFF", b" ")
    fallback_text = "".join(chr(byte) if 32 <= byte <= 126 else " " for byte in sanitized)
    return _extract_material_id_from_text(fallback_text)


def is_uid_fallback_payload(payload: Optional[Dict[str, Any]]) -> bool:
    raw = (payload or {}).get("raw")
    return isinstance(raw, dict) and raw.get("material_id_source") == "uid"


def has_readable_text_payload(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    text = payload.get("text")
    return isinstance(text, str) and bool(text.strip()) and not is_uid_fallback_payload(payload)


class PN532NFCReader(BaseNFCReader):
    """PN532 真读卡器，支持 I2C 或 SPI。"""

    def __init__(
        self,
        transport: BasePN532Transport,
        pin_config: Optional[PN532PinConfig] = None,
        command_timeout: float = 1.0,
        scan_timeout: float = 1.5,
        read_window_pages: int = 16,
        mifare_start_block: int = 4,
        mifare_block_count: int = 4,
        mifare_key_a: Optional[bytes] = None,
        passive_activation_retries: int = 0xFF,
        fallback_to_uid: bool = True,
    ):
        self.transport = transport
        self.pin_config = _coerce_pin_config(transport.interface, pin_config)
        self.command_timeout = max(0.1, float(command_timeout))
        self.scan_timeout = max(0.1, float(scan_timeout))
        self.read_window_pages = max(4, int(read_window_pages))
        self.mifare_start_block = int(mifare_start_block)
        self.mifare_block_count = max(1, int(mifare_block_count))
        self.mifare_key_a = bytes(mifare_key_a or b"\xFF\xFF\xFF\xFF\xFF\xFF")
        self.passive_activation_retries = int(passive_activation_retries) & 0xFF
        self.fallback_to_uid = bool(fallback_to_uid)
        self._initialized = False
        self._firmware_info: Optional[Dict[str, int]] = None

    def close(self) -> None:
        self.transport.close()

    def read_result(self) -> NFCReadResult:
        raw = {
            "mode": f"pn532_{self.transport.interface}",
            "transport": self.transport.describe(),
            "pins": self.pin_config.to_dict(),
        }
        try:
            self._ensure_initialized()
            if self._firmware_info:
                raw["firmware"] = dict(self._firmware_info)
            target = self._list_passive_target()
            if target is None:
                return NFCReadResult(success=False, error="No NFC tag detected", raw=raw)

            uid_hex = target["uid"].hex().upper()
            raw["uid"] = uid_hex
            tag_data = self._read_tag_data_from_target(target)
            material_id = tag_data.get("material_id")
            tag_text = tag_data.get("text")
            if tag_data.get("payload_source"):
                raw["payload_source"] = tag_data["payload_source"]
            if tag_data.get("tag_text_source"):
                raw["tag_text_source"] = tag_data["tag_text_source"]
            if tag_text:
                raw["tag_text"] = tag_text
            if tag_data.get("payload_hex"):
                raw["tag_payload_hex"] = tag_data["payload_hex"]

            if material_id:
                raw["material_id_source"] = "tag_payload"
                return NFCReadResult(success=True, material_id=material_id, text=tag_text, raw=raw)

            if self.fallback_to_uid:
                raw["material_id_source"] = "uid"
                return NFCReadResult(success=True, material_id=uid_hex, text=tag_text, raw=raw)

            return NFCReadResult(
                success=False,
                material_id=None,
                text=tag_text,
                error="Unable to decode material_id from tag",
                raw=raw,
            )
        except Exception as exc:
            raw["error"] = str(exc)
            return NFCReadResult(success=False, error=str(exc), raw=raw)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._firmware_info = self._get_firmware_version()
        self._call_function(0x14, bytes([0x01, 0x14, 0x01]))
        self._configure_passive_activation_retries(self.passive_activation_retries)
        self._initialized = True

    def _configure_passive_activation_retries(self, retries: int) -> None:
        self._call_function(
            0x32,
            bytes([0x05, 0xFF, 0x01, int(retries) & 0xFF]),
        )

    def _get_firmware_version(self) -> Dict[str, int]:
        data = self._call_function(0x02)
        if len(data) < 4:
            raise RuntimeError(f"Unexpected PN532 firmware response length: {len(data)}")
        return {
            "chip": int(data[0]),
            "version": int(data[1]),
            "revision": int(data[2]),
            "support": int(data[3]),
        }

    def _list_passive_target(self) -> Optional[Dict[str, Any]]:
        data = self._call_function(
            0x4A,
            bytes([0x01, PN532_MIFARE_ISO14443A]),
            response_timeout=self.scan_timeout,
        )
        if not data or data[0] == 0:
            return None
        if len(data) < 6:
            raise RuntimeError(f"Unexpected PN532 target response length: {len(data)}")

        uid_length = int(data[5])
        uid_start = 6
        uid_end = uid_start + uid_length
        if uid_end > len(data):
            raise RuntimeError("PN532 target response does not contain full UID")

        return {
            "target_number": int(data[1]),
            "uid_length": uid_length,
            "uid": bytes(data[uid_start:uid_end]),
            "raw": bytes(data),
        }

    def _build_tag_data(self, payload: bytes, payload_source: str) -> Dict[str, Optional[str]]:
        tag_text = extract_text_from_payload(payload)
        return {
            "material_id": extract_material_id_from_payload(payload),
            "text": tag_text,
            "tag_text_source": "payload" if tag_text else None,
            "payload_source": payload_source,
            "payload_hex": payload.hex().upper() if payload else None,
        }

    def _read_tag_data_from_target(self, target: Dict[str, Any]) -> Dict[str, Optional[str]]:
        uid = bytes(target["uid"])
        uid_length = int(target.get("uid_length", len(uid)))
        target_number = int(target["target_number"])

        if uid_length == 4 and self._mifare_authenticate(
            target_number=target_number,
            block=self.mifare_start_block,
            uid=uid,
            key=self.mifare_key_a,
        ):
            payload = bytearray()
            for block in range(
                self.mifare_start_block,
                self.mifare_start_block + self.mifare_block_count,
            ):
                chunk = self._mifare_read_block(target_number=target_number, block=block)
                if chunk:
                    payload.extend(chunk)

            if payload:
                tag_data = self._build_tag_data(bytes(payload), payload_source="mifare_block")
                if tag_data.get("material_id") or tag_data.get("text"):
                    return tag_data

        payload = bytearray()
        for page in range(4, 4 + self.read_window_pages, 4):
            try:
                chunk = self._in_data_exchange(target_number, bytes([MIFARE_CMD_READ, page]))
            except RuntimeError:
                continue
            if chunk:
                payload.extend(chunk[:16])

        return self._build_tag_data(bytes(payload), payload_source="page_window")

    def _mifare_authenticate(self, target_number: int, block: int, uid: bytes, key: bytes) -> bool:
        response = self._call_function(
            0x40,
            bytes([target_number, MIFARE_CMD_AUTH_A, int(block) & 0xFF]) + bytes(key[:6]) + bytes(uid),
            response_timeout=self.scan_timeout,
        )
        return bool(response) and response[0] == 0x00

    def _mifare_read_block(self, target_number: int, block: int) -> Optional[bytes]:
        response = self._call_function(
            0x40,
            bytes([target_number, MIFARE_CMD_READ, int(block) & 0xFF]),
            response_timeout=self.scan_timeout,
        )
        if not response or response[0] != 0x00:
            return None
        return bytes(response[1:17])

    def _in_data_exchange(self, target_number: int, payload: bytes) -> bytes:
        response = self._call_function(
            0x40,
            bytes([target_number]) + payload,
            response_timeout=self.scan_timeout,
        )
        if not response:
            raise RuntimeError("PN532 returned empty InDataExchange response")

        status = response[0]
        if status != 0x00:
            raise RuntimeError(f"PN532 target exchange failed: status=0x{status:02X}")
        return bytes(response[1:])

    def _call_function(
        self,
        command: int,
        data: bytes = b"",
        response_timeout: Optional[float] = None,
    ) -> bytes:
        frame = self._build_frame(command, data)
        self.transport.write_frame(frame)

        if not self.transport.wait_ready(self.command_timeout):
            raise RuntimeError("PN532 ACK timeout")
        ack = self.transport.read_data(len(PN532_ACK_FRAME))
        if ack != PN532_ACK_FRAME:
            raise RuntimeError(f"Unexpected PN532 ACK frame: {ack.hex()}")

        if not self.transport.wait_ready(response_timeout or self.command_timeout):
            raise RuntimeError("PN532 response timeout")
        return self._read_response(command)

    def _read_response(self, command: int) -> bytes:
        full_frame = self.transport.read_full_response(command)
        if full_frame is None:
            header = self.transport.read_data(6)
            if len(header) != 6 or header[:3] != b"\x00\x00\xFF":
                raise RuntimeError(f"Invalid PN532 response header: {header.hex()}")

            length = header[3]
            length_checksum = header[4]
            if ((length + length_checksum) & 0xFF) != 0:
                raise RuntimeError("PN532 response length checksum mismatch")
            if length in (0x00, 0xFF):
                raise RuntimeError("PN532 empty or extended frames are not supported here")

            remainder = self.transport.read_data(length + 1)
            full_frame = header + remainder

        if len(full_frame) < 7 or full_frame[:3] != b"\x00\x00\xFF":
            raise RuntimeError(f"Invalid PN532 response header: {full_frame.hex()}")

        length = full_frame[3]
        length_checksum = full_frame[4]
        if ((length + length_checksum) & 0xFF) != 0:
            raise RuntimeError("PN532 response length checksum mismatch")
        if length in (0x00, 0xFF):
            raise RuntimeError("PN532 empty or extended frames are not supported here")
        if len(full_frame) < length + 7:
            raise RuntimeError(
                f"PN532 response frame shorter than expected: need {length + 7}, got {len(full_frame)}"
            )

        payload = full_frame[5:5 + length]
        dcs = full_frame[5 + length]
        postamble = full_frame[6 + length]
        if ((sum(payload) + dcs) & 0xFF) != 0:
            raise RuntimeError("PN532 response data checksum mismatch")
        if postamble != 0x00:
            raise RuntimeError("PN532 response postamble is invalid")
        if len(payload) < 2:
            raise RuntimeError("PN532 response payload is too short")
        if payload[0] != 0xD5:
            raise RuntimeError(f"Unexpected PN532 response TFI: 0x{payload[0]:02X}")

        expected_response = (int(command) + 1) & 0xFF
        if payload[1] != expected_response:
            raise RuntimeError(
                f"Unexpected PN532 response code: expected 0x{expected_response:02X}, got 0x{payload[1]:02X}"
            )
        return bytes(payload[2:])

    @staticmethod
    def _build_frame(command: int, data: bytes) -> bytes:
        payload = bytes([0xD4, int(command) & 0xFF]) + bytes(data)
        length = len(payload) & 0xFF
        length_checksum = (-length) & 0xFF
        data_checksum = (-sum(payload)) & 0xFF
        return b"\x00\x00\xFF" + bytes([length, length_checksum]) + payload + bytes([data_checksum, 0x00])


def create_nfc_reader(
    backend: str,
    material_ids: Optional[List[str]] = None,
    file_path: Optional[str] = None,
    command: Optional[str] = None,
    i2c_bus: int = 1,
    i2c_address: int = 0x24,
    spi_bus: int = 0,
    spi_device: int = 0,
    spi_speed_hz: int = 1_000_000,
    uart_port: str = "/dev/ttyS1",
    uart_baudrate: int = 115200,
    command_timeout: float = 1.0,
    scan_timeout: float = 1.5,
    read_window_pages: int = 16,
    passive_activation_retries: int = 0xFF,
    fallback_to_uid: bool = True,
    pin_config: Optional[Any] = None,
) -> BaseNFCReader:
    """根据参数创建共享 NFC 读卡器。"""
    if backend == "mock":
        return MockNFCReader(material_ids=material_ids)
    if backend == "file":
        if not file_path:
            raise ValueError("file backend requires --file-path")
        return FileNFCReader(file_path=file_path)
    if backend == "command":
        if not command:
            raise ValueError("command backend requires --command")
        return CommandNFCReader(command=command)
    if backend == "pn532_i2c":
        transport = PN532I2CTransport(bus_id=i2c_bus, address=i2c_address)
        return PN532NFCReader(
            transport=transport,
            pin_config=_coerce_pin_config("i2c", pin_config),
            command_timeout=command_timeout,
            scan_timeout=scan_timeout,
            read_window_pages=read_window_pages,
            passive_activation_retries=passive_activation_retries,
            fallback_to_uid=fallback_to_uid,
        )
    if backend == "pn532_spi":
        transport = PN532SPITransport(
            bus=spi_bus,
            device=spi_device,
            speed_hz=spi_speed_hz,
        )
        return PN532NFCReader(
            transport=transport,
            pin_config=_coerce_pin_config("spi", pin_config),
            command_timeout=command_timeout,
            scan_timeout=scan_timeout,
            read_window_pages=read_window_pages,
            passive_activation_retries=passive_activation_retries,
            fallback_to_uid=fallback_to_uid,
        )
    if backend == "pn532_uart":
        transport = PN532UARTTransport(
            port=uart_port,
            baudrate=uart_baudrate,
            timeout=min(command_timeout, 0.2),
        )
        return PN532NFCReader(
            transport=transport,
            pin_config=_coerce_pin_config("uart", pin_config),
            command_timeout=command_timeout,
            scan_timeout=scan_timeout,
            read_window_pages=read_window_pages,
            passive_activation_retries=passive_activation_retries,
            fallback_to_uid=fallback_to_uid,
        )
    raise ValueError(f"Unsupported NFC backend: {backend}")


__all__ = [
    "NFCReadResult",
    "BaseNFCReader",
    "MockNFCReader",
    "FileNFCReader",
    "CommandNFCReader",
    "PN532PinConfig",
    "PN532I2CTransport",
    "PN532SPITransport",
    "PN532UARTTransport",
    "PN532NFCReader",
    "extract_text_from_payload",
    "extract_material_id_from_payload",
    "create_nfc_reader",
]
