<img src="https://count.getloli.com/@nagatoquin33?name=nagatoquin33&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">
# AstrBot 群聊上下班插件

一个用于 AstrBot 的群聊状态控制插件。你可以在每个群里单独发送 `下班` 让机器人停止响应其他功能，再发送 `上班` 重新启用。

## 功能

- 分群独立控制，不同群互不影响
- 下班后拦截当前群的后续消息，避免触发其他插件或 LLM
- 保留 `上班` 指令，方便随时恢复机器人响应

## 指令

| 指令 | 作用 | 说明 |
| --- | --- | --- |
| `下班` | 关闭当前群聊的机器人功能 | 关闭后，该群里的大部分消息都会被拦截 |
| `上班` | 恢复当前群聊的机器人功能 | 恢复后，机器人重新响应该群消息 |

> 这两个指令仅允许 AstrBot 全局配置 `admins_id` 中的管理员使用。

## 安装

1. 将插件文件放入 AstrBot 的插件目录。
2. 确认插件入口文件为 `main.py`。
3. 重启 AstrBot 或在后台重新加载插件。

### `main.py`

插件通过群 ID 记录每个群的状态：

- `下班` 时，把当前群加入“停用”列表
- `上班` 时，把当前群从“停用”列表移除
- 处于“下班”状态时，除 `上班` 外的消息都会被拦截

## 原理

这个插件使用 AstrBot 的消息事件监听机制，在群聊消息进入后尽早判断当前群是否处于“下班”状态。如果是，则调用事件拦截，阻止后续插件链和模型回复继续执行。

## 使用示例

在群里发送：

```text
下班
```

随后机器人将停止响应该群的其他消息。

再次发送：

```text
上班
```

机器人恢复正常工作。

## 注意事项

- 该插件默认只对群聊生效
- “下班”状态是按群保存的，不会影响其他群
- 如果 AstrBot 的事件接口版本升级，可能需要同步调整监听器写法

## 开源说明

你可以自由修改和分发本插件。建议保留原作者信息与项目说明，方便后续维护和交流。
<img src="https://count.getloli.com/@nagatoquin33?name=nagatoquin33&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">
