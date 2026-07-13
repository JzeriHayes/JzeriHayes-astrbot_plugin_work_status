from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class WorkStatusPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.admins_id = context.get_config().get("admins_id", [])
        self.off_groups: set[str] = set()

    def _get_group_id(self, event: AstrMessageEvent) -> str:
        message_obj = getattr(event, "message_obj", None)
        if not message_obj:
            return ""
        return str(getattr(message_obj, "group_id", "") or "")

    def _get_message_text(self, event: AstrMessageEvent) -> str:
        return (getattr(event, "message_str", "") or "").strip()

    def is_admin(self, event: AstrMessageEvent) -> bool:
        if not self.admins_id:
            return True
        return str(event.get_sender_id()) in [str(uid) for uid in self.admins_id]

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def block_when_off(self, event: AstrMessageEvent):
        """下班状态下拦截当前群的后续插件、指令和 LLM 处理。"""
        group_id = self._get_group_id(event)
        if not group_id or group_id not in self.off_groups:
            return

        # 放行上班指令，否则下班后无法恢复。
        if self._get_message_text(event) in {"上班", "/上班"}:
            return

        event.stop_event()

    @filter.command("上班", priority=101)
    async def turn_on(self, event: AstrMessageEvent):
        """开启当前群聊的机器人功能。"""
        if not self.is_admin(event):
            yield event.plain_result("我不认识你，我不要上班")
            return

        group_id = self._get_group_id(event)
        if not group_id:
            yield event.plain_result("该指令仅支持在群聊中使用。")
            return

        self.off_groups.discard(group_id)
        yield event.plain_result("呜呜，又要上班了")

    @filter.command("下班", priority=101)
    async def turn_off(self, event: AstrMessageEvent):
        """关闭当前群聊的机器人功能。"""
        if not self.is_admin(event):
            yield event.plain_result("只有 AstrBot 设置中的管理员可以使用这个指令。")
            return

        group_id = self._get_group_id(event)
        if not group_id:
            yield event.plain_result("该指令仅支持在群聊中使用。")
            return

        self.off_groups.add(group_id)
        yield event.plain_result("好耶，下班啦！")