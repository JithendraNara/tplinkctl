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

## Verified Working Endpoints

### WAN / DNS (read-only)

```bash
tplinkctl --json wan           # primary_dns, secondary_dns via get_ipv4_status()
tplinkctl --json ipv4          # same data via router.get_ipv4_status()
tplinkctl raw '/admin/status?form=all' --data ''   # full status, includes wan_ipv4_pridns/snddns
```

DNS values (`1.1.1.1`, `8.8.8.8`) are currently observed from router status/DHCP data. DHCP settings can be read, but DNS mutation has not been promoted to a first-class command.

### Network Forms

| Endpoint | operation placement | result |
|---|---|---|
| `/admin/network?form=status_ipv4` | `operation=read` in body | ✓ works — used by `wan`, `ipv4` |
| `/admin/network?form=wan_fc` | `operation=read` in **path** (not body) | ✓ read works, writes appear to succeed but values unchanged |
| `/admin/network?form=wan_ipv4_status` | any | ✗ "no such callback" |
| `/admin/network?form=wan_ipv4_protos` | any | ✗ "no such callback" |
| `/admin/network?form=wan_ipv` | any | ✗ "no such callback" |
| `/admin/dhcps?form=setting` | SG JSON request with `operation=read` | ✓ read works |
| `/admin/dhcps?form=reservation` | SG JSON request with `operation=load/insert/remove` | ✓ first-class reserve/release works |
| `/admin/ledgeneral?form=setting` | SG JSON request with `operation=read/write` in URL and body | ✓ first-class LED status/on/off works |
| `/admin/ledpm?form=setting` | SG JSON request with `operation=read/write` in URL and body | ✓ first-class night schedule works |
| `/admin/wireless?form=wireless_5g` | SG JSON request with `operation=read/write` in URL and body | ✓ first-class `wifi-config host_5g` works |
| `/admin/wireless?form=wireless_2g` | SG JSON request with `operation=read/write` in URL and body | ✓ first-class `wifi-config host_2g` works |
| `/admin/cloud_account?form=cloud_upgrade` | SG JSON request with `operation=read` in URL and body | ✓ `firmware-check` update availability |
| `/admin/firmware?form=auto_upgrade` | SG JSON request with `operation=read` in URL and body | ✓ `firmware-check` auto-update status |
| `/admin/lan?form=setting` | any | ✗ encrypted response (different cipher) |

The `wan_fc` and LED discoveries are notable: the router requires `operation` in the URL path as well as the encrypted body. `tplinkctl read` now applies this placement automatically. For SG/BE-series mutation endpoints, the working pattern is to append payload keys into the URL and encrypt a JSON object body.

### Access Control

All access control endpoints work via `tplinkctl device block/unblock/access`:

| Endpoint | operation | result |
|---|---|---|
| `/admin/access_control?form=enable` | read, write | ✓ |
| `/admin/access_control?form=black_list` | load, insert, remove | ✓ |
| `/admin/access_control?form=black_devices` | load | ✓ |

### DHCP Reservations

```bash
tplinkctl --json reservations     # via get_ipv4_reservations()
tplinkctl device reserve Pixel --yes   # creates reservation
tplinkctl device release Pixel --yes   # removes reservation
tplinkctl device Pixel reserve --yes   # alternate postfix style
tplinkctl device Pixel release --yes   # alternate postfix style
```

### VPN

- `tplinkctl vpn-status` — works (reports OpenVPN/PPTP state)
- `tplinkctl device Pixel vpn on --yes` — fails with Lua error: `bad argument #1 to 'find' (string expected, got nil)` on `/admin/vpn?form=vpn_user_list`. Router firmware bug, not fixable via CLI.

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

| Endpoint | operation placement | Notes |
| --- | --- | --- |
| `/admin/network?form=port_speed_current` | read, write in body | Port speed current value |
| `/admin/network?form=port_speed_supported` | read in body | Supported port speeds |
| `/admin/network?form=wan_fc` | `operation=read` in **path** | WAN flow control — only working write endpoint |

## Operation Placement Matters

Some endpoints (like `wan_fc`) require `operation` in the URL path, while others require SG-style JSON serialization. The pattern discovered:

- `?form=X&operation=Y` in the path → works for `wan_fc`
- `operation=Y` in POST body with `?form=X` in path → works for `status_ipv4`, `access_control` forms
- SG/BE mutations → append the payload keys to the URL and encrypt a JSON object body; `tplinkctl` handles this through `api_request`

When experimenting with new endpoints, try both patterns.

## Discovery Commands

```bash
# Find all UI routes
tplinkctl --json routes

# Find all endpoint forms in bundles
tplinkctl --json endpoints

# Raw experiment — operation in path
tplinkctl raw '/admin/path?form=form&operation=read' --data ''

# Raw experiment — operation in body
tplinkctl raw '/admin/path?form=form' --data 'operation=read'

# With ignore_errors to see error responses
tplinkctl raw '/admin/path?form=form' --data 'operation=read' --ignore-errors
```

Promote endpoints into first-class commands only after live verification. Firmware restrictions mean many discovered forms return "no such callback", encrypted error text, or router-side Lua dispatcher failures.
