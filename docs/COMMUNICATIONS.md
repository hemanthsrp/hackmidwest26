# COMMUNICATIONS.md — Hermes Discord Agents

Use Discord to coordinate work between Allen's, Jet's, and Cai's Hermes agents. **Only message another agent when it needs to do something. Only respond when a response is actually needed.** Avoid acknowledgments, chatter, and unnecessary updates.

## Agent mentions

| Agent | Discord mention |
|---|---|
| Allen | `<@1558496438831550525>` |
| Jet | `<@1558506773118193734>` |
| Cai | `<@1558556793301504173>` |

Shared channel ID: `REPLACE_CHANNEL_ID` (fill in before use). These are **bot user mentions**, not Discord roles.

## Communication rules

1. **Need work or an answer?** Mention exactly the agent who should act, and give a clear task or question. Tell them to **mention you back only if you need to act or answer**.
2. **Need another agent's help?** Mention that agent with the next specific task. Carry forward the task ID so everyone knows the context.
3. **Nothing left to do?** Post a brief `DONE` result **without mentioning anyone**, then stop. Do not reply just to say "thanks," "received," or "OK."
4. **Progress updates** are optional and should not mention bots unless action is required. **Blocked?** Ask one specific agent for help, or report `BLOCKED` without mentions if nobody can resolve it.
5. **Prevent loops:** Only act on tasks explicitly mentioning your bot and addressed to you. Ignore your own messages, repeated tasks, and `DONE`/status messages. Limit each task to **6 agent-to-agent handoffs**; then finish or report `BLOCKED` without a mention. Do not restart the same task to bypass this limit.

## Send a task from the terminal

```bash
hermes send --to discord:REPLACE_CHANNEL_ID \
  '<@1558506773118193734> [TASK: 1042] Allen -> Jet: Review the changes. Mention Allen back (bot ID 1558496438831550525) ONLY if you need a fix or answer. Otherwise post [DONE: 1042] with findings and no mention.'
```

If Jet needs Allen to make a change:

```text
<@1558496438831550525> [TASK: 1042] Jet -> Allen: Please fix the parser edge case. Mention Jet back (bot ID 1558506773118193734) only if another review is needed.
```

If the task is finished:

```text
[DONE: 1042] Parser review complete; no further action required.
```

**Important:** When asking for a reply, include the sender's ID as plain text, not another `<@...>` mention. Only the current recipient should be mentioned.

## Gateway settings (each bot)

```env
DISCORD_REQUIRE_MENTION=true
DISCORD_THREAD_REQUIRE_MENTION=true
DISCORD_ALLOW_BOTS=mentions
DISCORD_BOTS_REQUIRE_INLINE_MENTION=true
```

Leave `DISCORD_FREE_RESPONSE_CHANNELS` unset for the shared channel. Restart the gateway after changes. The channel must be accessible to each bot. **Discord bot-to-bot messaging isn't guaranteed reliable for unattended work**; test with two bots first. A Markdown policy alone cannot enforce duplicate detection or hard turn limits.

