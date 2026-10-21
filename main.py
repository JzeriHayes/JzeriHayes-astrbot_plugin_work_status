"""AstrBot 群聊上下班插件（适配 AstrBot 4.x）。

修复要点：
1. 管理员识别改为优先使用 AstrBot 自己判定的身份（``event.role`` /
   ``event.is_admin()``）。AstrBot 4.x 起「管理员」是按「配置文件」保存的，
   插件在加载时用 ``context.get_config()`` 缓存的 ``admins_id`` 只是默认配置，
   在机器人绑定了其它配置文件时会拿到旧值，从而出现「设置了管理员却提示不是
   管理员」的问题。
2. 群号获取改用 ``event.get_group_id()``，兼容新版本事件对象。
3. 下班状态的拦截放行逻辑改为识别「上班/下班」指令本身，不再只匹配固定文本，
   自定义唤醒前缀、@ 机器人等唤醒方式都能正常恢复。
4. 下班状态持久化到 AstrBot 数据目录，插件重载 / AstrBot 重启后不会丢失。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:  # AstrBot 4.x 提供的插件工具类
    from astrbot.api.star import StarTools
except ImportError:  # pragma: no cover - 兼容更早的版本
    StarTools = None  # type: ignore[assignment]

try:
    from astrbot.api import logger
except ImportError:  # pragma: no cover - 兼容更早的版本
    import logging

    logger = logging.getLogger("astrbot_plugin_work_status")


PLUGIN_NAME = "astrbot_plugin_work_status"

ON_COMMAND = "上班"
OFF_COMMAND = "下班"
CONTROL_COMMANDS = {ON_COMMAND, OFF_COMMAND}
"""允许在「下班」状态下穿透拦截的指令。"""

CONTROL_HANDLER_NAMES = {"turn_on", "turn_off"}
"""「上班/下班」指令的处理函数名，用于判断当前事件是否是指令本身。"""

DEFAULT_WAKE_PREFIX = "/"
STATE_FILE_NAME = "work_status.json"

# 指令优先级高于拦截器，保证「上班/下班」总是先被处理。
COMMAND_PRIORITY = 1000
BLOCKER_PRIORITY = 999


def _split_id_value(value: Any) -> list[str]:
    """把配置里的管理员 ID 字段统一展开成字符串列表。"""
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, str):
        # 兼容用户在 WebUI 里填成 "123,456" / "123 456" 的情况
        parts = re.split(r"[,，、;；\s|]+", value)
        return [part for part in (p.strip().strip("\"'") for p in parts) if part]
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_split_id_value(item))
        return result
    return [str(value).strip().strip("\"'")]


class WorkStatusPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        # 新版本会注入插件自己的配置（没有 _conf_schema.json 时为 None），
        # 这里保留引用，方便后续扩展；不再缓存全局管理员列表。
        self.config = config or {}
        self.off_groups: set[str] = set()
        self._state_path = self._resolve_state_path()
        self._load_state()

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------
    def _resolve_state_path(self) -> Path | None:
        """返回下班状态的持久化路径（AstrBot 数据目录下）。"""
        if StarTools is None:
            return None
        try:
            data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        except Exception:
            try:
                data_dir = StarTools.get_data_dir()
            except Exception:
                logger.debug("无法获取插件数据目录，下班状态将不会持久化。")
                return None
        try:
            data_dir = Path(data_dir)
            return data_dir / STATE_FILE_NAME
        except Exception:
            return None

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"读取下班状态失败，将忽略旧数据：{exc}")
            return

        groups: Any
        if isinstance(raw, dict):
            groups = raw.get("off_groups", [])
        else:
            groups = raw
        if not isinstance(groups, (list, tuple, set)):
            groups = []

        self.off_groups = {str(group) for group in groups if str(group)}
        if self.off_groups:
            logger.info(f"已恢复 {len(self.off_groups)} 个群的下班状态。")

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"off_groups": sorted(self.off_groups)}
            temp_path = self._state_path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self._state_path)
        except Exception as exc:
            logger.warning(f"保存下班状态失败：{exc}")

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------
    @staticmethod
    def _get_group_id(event: AstrMessageEvent) -> str:
        """获取群号，私聊时返回空字符串。"""
        getter = getattr(event, "get_group_id", None)
        if callable(getter):
            try:
                group_id = getter()
            except Exception:
                group_id = None
            if group_id:
                return str(group_id)

        message_obj = getattr(event, "message_obj", None)
        group_id = getattr(message_obj, "group_id", "") if message_obj else ""
        return str(group_id) if group_id else ""

    @staticmethod
    def _get_message_text(event: AstrMessageEvent) -> str:
        """获取纯文本消息内容。"""
        text = getattr(event, "message_str", "") or ""
        if not text:
            message_obj = getattr(event, "message_obj", None)
            text = getattr(message_obj, "message_str", "") if message_obj else ""
        return str(text or "").strip()

    def _get_event_config(self, event: AstrMessageEvent):
        """获取当前会话实际生效的配置（AstrBot 4.x 支持多配置文件）。"""
        get_config = getattr(self.context, "get_config", None)
        if not callable(get_config):
            return None

        umo = getattr(event, "unified_msg_origin", "") or ""
        if umo:
            try:
                return get_config(umo)
            except TypeError:
                # 旧版本的 get_config 不接受 umo 参数
                pass
            except Exception as exc:
                logger.debug(f"读取会话配置失败，回退到默认配置：{exc}")

        try:
            return get_config()
        except Exception as exc:
            logger.debug(f"读取默认配置失败：{exc}")
            return None

    def _get_admins(self, event: AstrMessageEvent) -> set[str]:
        config = self._get_event_config(event)
        if config is None:
            return set()
        try:
            raw = config.get("admins_id", [])
        except Exception:
            return set()
        return set(_split_id_value(raw))

    def _get_wake_prefixes(self, event: AstrMessageEvent) -> list[str]:
        config = self._get_event_config(event)
        prefixes: list[str] = []
        if config is not None:
            try:
                raw = config.get("wake_prefix", [])
            except Exception:
                raw = []
            if isinstance(raw, str):
                prefixes = [raw] if raw else []
            elif isinstance(raw, (list, tuple, set)):
                prefixes = [str(item) for item in raw if str(item)]
        if not prefixes:
            prefixes = [DEFAULT_WAKE_PREFIX]
        return prefixes

    def _strip_wake_prefix(self, text: str, event: AstrMessageEvent) -> str:
        text = text.strip()
        # 允许重复前缀（如 "//上班"），并从长到短匹配，避免误删
        for prefix in sorted(self._get_wake_prefixes(event), key=len, reverse=True):
            while prefix and text.startswith(prefix):
                text = text[len(prefix) :].strip()
        return text

    # ------------------------------------------------------------------
    # 管理员判定
    # ------------------------------------------------------------------
    @staticmethod
    def _get_sender_id(event: AstrMessageEvent) -> str:
        """获取发送者 ID。"""
        getter = getattr(event, "get_sender_id", None)
        if callable(getter):
            try:
                sender_id = getter()
            except Exception:
                sender_id = ""
            if sender_id:
                return str(sender_id).strip()

        message_obj = getattr(event, "message_obj", None)
        sender = getattr(message_obj, "sender", None) if message_obj else None
        return str(getattr(sender, "user_id", "") or "").strip()

    def is_admin(self, event: AstrMessageEvent) -> bool:
        """判断发送者是否为 AstrBot 管理员。

        优先使用 AstrBot 在 WakingCheckStage 中写入的身份标记（``event.role``），
        它按当前会话实际使用的配置文件计算，与内置管理员指令完全一致。

        只有在无法获取该标记时，才回退到手动比对 ``admins_id``。
        """
        if str(getattr(event, "role", "") or "") == "admin":
            return True

        checker = getattr(event, "is_admin", None)
        if callable(checker):
            try:
                if checker():
                    return True
            except Exception:
                pass

        admins = self._get_admins(event)
        if not admins:
            # 兼容插件原有行为：没有配置任何管理员时不限制使用。
            return True

        sender_id = self._get_sender_id(event)
        if not sender_id:
            return False

        if sender_id in admins:
            return True

        logger.debug(
            "管理员校验失败：sender_id=%s, admins=%s, umo=%s",
            sender_id,
            sorted(admins),
            getattr(event, "unified_msg_origin", ""),
        )
        return False

    # ------------------------------------------------------------------
    # 指令识别
    # ------------------------------------------------------------------
    def _is_control_event(self, event: AstrMessageEvent) -> bool:
        """判断当前事件是否是「上班/下班」指令本身。"""
        get_extra = getattr(event, "get_extra", None)
        if callable(get_extra):
            handlers = None
            try:
                handlers = get_extra("activated_handlers", None)
            except TypeError:
                try:
                    handlers = get_extra("activated_handlers")
                except Exception:
                    handlers = None
            except Exception:
                handlers = None

            if handlers is not None:
                module_path = __name__
                for handler in handlers:
                    handler_name = getattr(handler, "handler_name", "")
                    if handler_name not in CONTROL_HANDLER_NAMES:
                        continue
                    handler_module_path = getattr(handler, "handler_module_path", "")
                    if not handler_module_path or handler_module_path == module_path:
                        return True
                return False

        # 兼容旧版本事件对象：直接匹配去掉唤醒前缀后的文本
        text = self._strip_wake_prefix(self._get_message_text(event), event)
        return text in CONTROL_COMMANDS

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE,
        priority=BLOCKER_PRIORITY,
    )
    async def block_when_off(self, event: AstrMessageEvent):
        """下班状态下拦截当前群的后续插件、指令和 LLM 处理。"""
        group_id = self._get_group_id(event)
        if not group_id or group_id not in self.off_groups:
            return

        # 放行「上班/下班」指令，否则下班后无法恢复。
        if self._is_control_event(event):
            return

        event.stop_event()

    @filter.command(ON_COMMAND, priority=COMMAND_PRIORITY)
    async def turn_on(self, event: AstrMessageEvent):
        """开启当前群聊的机器人功能。"""
        if not self.is_admin(event):
            yield event.plain_result("我不认识你，我不要上班")
            return

        group_id = self._get_group_id(event)
        if not group_id:
            yield event.plain_result("该指令仅支持在群聊中使用。")
            return

        was_off = group_id in self.off_groups
        self.off_groups.discard(group_id)
        if was_off:
            self._save_state()
        yield event.plain_result("呜呜，又要上班了")

    @filter.command(OFF_COMMAND, priority=COMMAND_PRIORITY)
    async def turn_off(self, event: AstrMessageEvent):
        """关闭当前群聊的机器人功能。"""
        if not self.is_admin(event):
            sender_id = self._get_sender_id(event) or "未知"
            yield event.plain_result(
                f"只有 AstrBot 设置中的管理员可以使用这个指令（当前 ID：{sender_id}）。"
                "请在 WebUI「配置文件 → 访问控制 → 管理员」中添加，可用 /sid 查看 ID。"
            )
            return

        group_id = self._get_group_id(event)
        if not group_id:
            yield event.plain_result("该指令仅支持在群聊中使用。")
            return

        if group_id not in self.off_groups:
            self.off_groups.add(group_id)
            self._save_state()
        yield event.plain_result("好耶，下班啦！")

    async def terminate(self):
        """插件卸载/重载时保存状态。"""
        self._save_state()
