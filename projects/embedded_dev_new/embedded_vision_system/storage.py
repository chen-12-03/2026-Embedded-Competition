"""
统一数据存储路径管理。

目标：
- 板机上默认把所有运行期数据放到 TF 卡挂载目录
- 检测不到 TF 卡时拒绝启动，不回退到其他目录
- 避免相对路径写到当前目录或根目录
- 提供统一的截图、视频、状态文件、配置文件存储入口
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_ROOT_ENV = "EMBEDDED_VISION_DATA_ROOT"
TF_MEDIA_ROOT = Path("/run/media")
BOARD_DATA_ROOT = Path("/run/media/mmcblk1p1/embedded_vision_data")


class TFCardUnavailableError(RuntimeError):
    """未检测到 TF 卡挂载时抛出的异常。"""


def _find_tf_card_mount() -> Path | None:
    """查找当前已挂载的 TF 卡目录。"""
    if not TF_MEDIA_ROOT.exists():
        return None

    for candidate in sorted(TF_MEDIA_ROOT.glob("mmcblk*")):
        if candidate.is_dir():
            return candidate
    return None


def require_tf_card_mount() -> Path:
    """获取 TF 卡挂载目录；若不存在则直接报错。"""
    tf_mount = _find_tf_card_mount()
    if tf_mount is None:
        raise TFCardUnavailableError(
            "TF card mount not found under /run/media/mmcblk*. "
            "Refusing to start because all runtime data must be stored on TF card."
        )
    return tf_mount


def get_data_root(create: bool = True) -> Path:
    """获取统一数据根目录。"""
    tf_mount = require_tf_card_mount()
    env_value = os.environ.get(DATA_ROOT_ENV)

    if env_value:
        candidate = Path(env_value).expanduser()
        root = candidate if candidate.is_absolute() else tf_mount / candidate
        try:
            root.resolve().relative_to(tf_mount.resolve())
        except ValueError as exc:
            raise TFCardUnavailableError(
                f"{DATA_ROOT_ENV} must point inside TF card mount {tf_mount}, "
                f"got {root}"
            ) from exc
    else:
        root = tf_mount / "embedded_vision_data"

    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_subdir(*parts: str, create: bool = True) -> Path:
    """获取数据根目录下的子目录。"""
    target = get_data_root(create=create).joinpath(*parts)
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def get_data_path(*parts: str, create_parent: bool = True) -> Path:
    """获取数据根目录下的文件路径。"""
    target = get_data_root(create=create_parent).joinpath(*parts)
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def ensure_managed_path(
    raw_path: str | Path,
    default_subdir: str,
    create_parent: bool = True,
) -> Path:
    """
    将用户提供的路径约束到统一数据根目录内。

    规则：
    - 相对路径：放到 `<data_root>/<default_subdir>/...`
    - 绝对路径且已在 data_root 内：保留
    - 绝对路径但不在 data_root 内：改写到 `<data_root>/<default_subdir>/<basename>`
    """
    data_root = get_data_root(create=create_parent).resolve()
    candidate = Path(raw_path).expanduser()

    if candidate.is_absolute():
        try:
            candidate.resolve().relative_to(data_root)
            managed = candidate
        except ValueError:
            managed = data_root / default_subdir / candidate.name
            logger.warning(
                "Path %s is outside managed data root; redirected to %s",
                candidate,
                managed,
            )
    else:
        managed = data_root / default_subdir / candidate

    if create_parent:
        managed.parent.mkdir(parents=True, exist_ok=True)
    return managed


def describe_storage_root() -> str:
    """返回当前存储根目录字符串。"""
    return str(get_data_root(create=False))


__all__ = [
    "DATA_ROOT_ENV",
    "BOARD_DATA_ROOT",
    "TFCardUnavailableError",
    "require_tf_card_mount",
    "get_data_root",
    "get_subdir",
    "get_data_path",
    "ensure_managed_path",
    "describe_storage_root",
]
