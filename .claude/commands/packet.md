# /packet - Packet Status

Reports current packet state. Does not switch packets.

Required report:

PACKET_STATUS_REPORT
POVERTY_KILLER_PACKET: <value or UNSET>
POVERTY_KILLER_OVERRIDE: <value or UNSET>
POVERTY_KILLER_OVERRIDE_REASON: <present / absent>
pre_tool_use_hook: yes / no
post_tool_use_hook: yes / no
settings_hook_registered: yes / no

Packet scopes:
- G0: governance files only
- F4A: execution Decimal packet files only
- F4B: sentiment concurrency packet files only
- F4C: risk-state persistence packet files only
- UNSET: all writes blocked

Packet switching:
Operator must set environment variables before launching Claude Code. This command does not switch packets.

Override:
Emergency only. Must not be used for live mode, dependency changes, destructive git, or destructive deletes unless a separate explicit Board packet authorizes it.
