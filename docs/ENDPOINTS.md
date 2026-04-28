# Router UI Discovery

`tplinkctl` can inspect downloaded router JavaScript bundles and extract both UI routes and API-looking endpoints.

```bash
tplinkctl --json routes --name internet
tplinkctl --json endpoints --form network
```

## Current Router

The no-login `doctor` command detected:

- UI version: `BE220v1_1.11.0_2025-08-06T05:59:48.483Z`
- Runtime model from authenticated firmware: `Archer BE3500`
- Firmware: `1.1.3 Build 20251120 rel.38341(5553)`

## Internet Advanced Page

Route discovery maps `#/internetAdv` to:

```json
{
  "name": "internetAdv",
  "path": "internetAdv",
  "bundle": "index-BOBVatjl.js"
}
```

The `internetAdv` bundle references:

| Endpoint | Seen operation(s) | Notes |
| --- | --- | --- |
| `/admin/network?form=port_speed_current` | read, write | Port speed current value |
| `/admin/network?form=port_speed_supported` | read | Supported port speeds |
| `/admin/network?form=wan_fc` | read, write | WAN flow control in the UI |

Shared router bundles reference:

| Endpoint | Seen operation(s) | Notes |
| --- | --- | --- |
| `/admin/network?form=status_ipv4` | read | Works with `tplinkctl read` |
| `/admin/network?form=wan_ipv4_status` | read, request | Returns `no such callback` when read directly on this firmware |
| `/admin/network?form=wan_ipv4_protos` | request | Protocol list used by the UI |

Working direct read:

```bash
tplinkctl --json read '/admin/network?form=status_ipv4'
```

Some endpoints are UI-internal callbacks or require request payloads beyond `operation=read`. Keep `read`/`raw` as discovery tools, and promote endpoints into first-class commands only after live verification.
