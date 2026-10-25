# ADR 001: Preserve the VPN controller's SG form encoding

Status: accepted for read-only verification; VPN mutations remain experimental.

## Context

The SG request adapter converted every URL-encoded payload into JSON before
passing it to the upstream SDK for encryption. On a live Archer BE3500 running
firmware 1.3.5 Build 20260812, this caused authenticated VPN-client reads to
return `{"success": false, "errorcode": "no such callback"}`. The response
was encrypted, and the SDK's normal exception printed ciphertext, obscuring
this error. Historical notes incorrectly treated similar failures as proof of
a firmware bug.

Controlled, read-only A/B requests in the same authenticated session showed:

| Endpoint | JSON plaintext | Form plaintext |
| --- | --- | --- |
| `admin/vpn?form=enable` | `no such callback` | `enable: on` |
| `admin/vpn?form=server`, `load_basic` | `no such callback` | profile connection states |

The unmodified upstream `get_vpn_client_status()` also succeeded once its
form bodies were preserved. It reads `enable` with `read`, `server` with `load`,
and `vpn_user_list` with `load`. It returned enabled status, connected and
disconnected profiles, and an enabled device rule. No profile credentials,
certificates, private keys or live device identifiers belong in this document.

Putting `operation=read` / `load_basic` into the URL with an empty JSON body
also worked for those probes, but retaining the upstream form body is simpler
and avoids adding a retry or changing the URL.

## Decision

Exclude the exact `admin/vpn` controller from the SG query-to-JSON normalizer.
Preserve supplied form data, explicit JSON probes, and request flags. Keep
existing JSON behavior for all other controllers, including `admin/vpnconn`
and the separate VPN-server controllers. No broad automatic fallback/retry is
introduced: retrying a mutation with different serialization would be unsafe.

The second transport path, `api_request`, also converted forms into JSON and
copied fields into the URL. Its VPN calls now delegate to `router.request`,
so doctor/raw/device helpers share the same encoding contract as upstream
status reads. This avoids copying VPN payload fields into URLs. Live VPN
writes were not tested and are not advertised as live-verified.

## Verification

- A new regression runs the real upstream SG request, encryption and response
  decoding against an HTTP-boundary fixture and inspects the decrypted wire
  body. It failed before the fix (`{"operation": "read"}` instead of
  `operation=read`) and passed after it.
- Companion coverage retains non-VPN JSON behavior and explicit JSON/error
  flags, including positional `ignore_response` and `ignore_errors` calls.
- Live `vpn-client-status` succeeds through the normal CLI lifecycle, including
  logout. The live read-only `doctor --deep` passes all 10 probes, including
  both VPN client status and VPN device-list reads.
- All 95 unit tests and `make smoke` pass locally. No VPN configuration was
  toggled or rewritten.

A profile reporting `connected` is router control-plane evidence, not a test
of a particular client's public egress, kill switch or reachability. Likewise,
a single device using ISP egress does not show that router VPN is globally off.
Older firmware has not been retested; previous failures must not be assumed to
share this cause without the same controlled encoding check.
