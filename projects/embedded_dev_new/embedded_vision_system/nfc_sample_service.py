"""NFC 实时采样服务。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .hardware.nfc import BaseNFCReader, MockNFCReader, has_readable_text_payload

logger = logging.getLogger(__name__)


class NFCSampleService:
    """独立于分拣主流程的 NFC 采样状态服务。"""

    def __init__(
        self,
        reader: BaseNFCReader,
        poll_interval: float = 0.8,
        enabled: bool = True,
        poll_mock: bool = False,
    ):
        self.reader = reader
        self.poll_interval = max(0.2, float(poll_interval))
        self.enabled = bool(enabled)
        self.poll_mock = bool(poll_mock)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_sample_at: Optional[str] = None
        self._source = "idle"
        self._latched_readable_result: Optional[Dict[str, Any]] = None
        self._latched_readable_sample_at: Optional[str] = None
        self._latched_readable_source: Optional[str] = None
        self._latched_readable_consumed = False
        self._suspended = False
        self._suspend_reason: Optional[str] = None

    def _should_poll(self) -> bool:
        if not self.enabled:
            return False
        if self._suspended:
            return False
        if isinstance(self.reader, MockNFCReader) and not self.poll_mock:
            return False
        return True

    def start(self):
        if not self._should_poll():
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="nfc-sample-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                with self._read_lock:
                    payload = self.reader.read()
            except Exception as exc:
                logger.exception("NFC polling failed")
                payload = {
                    "success": False,
                    "error": str(exc),
                }
            self.publish_result(payload, source="poll")
            if self._stop_event.wait(self.poll_interval):
                break

    def publish_result(self, payload: Optional[Dict[str, Any]], source: str = "manual"):
        sample_at = datetime.now().isoformat()
        normalized = dict(payload or {})
        with self._lock:
            self._last_result = normalized
            self._last_sample_at = sample_at
            self._source = source
            if has_readable_text_payload(normalized):
                if (
                    not self._latched_readable_consumed
                    or not self._same_latched_readable_identity_locked(normalized)
                ):
                    self._latched_readable_result = dict(normalized)
                    self._latched_readable_sample_at = sample_at
                    self._latched_readable_source = source
                    self._latched_readable_consumed = False
            elif self._latched_readable_consumed:
                self._clear_latched_readable_locked()

    def sample_once(self) -> Dict[str, Any]:
        with self._read_lock:
            payload = self.reader.read()
        self.publish_result(payload, source="manual_sample")
        return payload

    def peek_result(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sample": dict(self._last_result or {}) or None,
                "sampled_at": self._last_sample_at,
                "source": self._source,
            }

    def peek_latched_result(self) -> Dict[str, Any]:
        with self._lock:
            latched = (
                dict(self._latched_readable_result or {})
                if self._latched_readable_result and not self._latched_readable_consumed
                else None
            )
            return {
                "sample": latched,
                "sampled_at": self._latched_readable_sample_at if latched else None,
                "source": self._latched_readable_source if latched else None,
            }

    def mark_latched_result_consumed(self, sampled_at: Optional[str] = None) -> bool:
        with self._lock:
            if self._latched_readable_result is None or self._latched_readable_consumed:
                return False
            if (
                sampled_at
                and self._latched_readable_sample_at
                and sampled_at != self._latched_readable_sample_at
            ):
                return False
            self._latched_readable_consumed = True
            return True

    def suspend(self, reason: str = "runtime_active") -> None:
        self._suspended = True
        self._suspend_reason = reason
        self.stop()

    def resume(self) -> None:
        self._suspended = False
        self._suspend_reason = None
        self.start()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            result = dict(self._last_result or {})
            sampled_at = self._last_sample_at
            source = self._source
            latched = (
                dict(self._latched_readable_result or {})
                if self._latched_readable_result and not self._latched_readable_consumed
                else None
            )
            latched_sampled_at = self._latched_readable_sample_at if latched else None
            latched_source = self._latched_readable_source if latched else None
            latched_consumed = self._latched_readable_consumed

        return {
            "enabled": self.enabled,
            "running": self._thread is not None and self._thread.is_alive(),
            "polling": self._should_poll(),
            "suspended": self._suspended,
            "suspend_reason": self._suspend_reason,
            "backend": type(self.reader).__name__,
            "sample": result or None,
            "sampled_at": sampled_at,
            "source": source,
            "latched_sample": latched,
            "latched_sampled_at": latched_sampled_at,
            "latched_source": latched_source,
            "latched_consumed": latched_consumed,
        }

    def _clear_latched_readable_locked(self) -> None:
        self._latched_readable_result = None
        self._latched_readable_sample_at = None
        self._latched_readable_source = None
        self._latched_readable_consumed = False

    def _same_latched_readable_identity_locked(self, payload: Dict[str, Any]) -> bool:
        if not self._latched_readable_result:
            return False
        return (
            self._latched_readable_result.get("material_id"),
            self._latched_readable_result.get("text"),
        ) == (
            payload.get("material_id"),
            payload.get("text"),
        )
