# ansible-himmelblau

Deploy and configure [Himmelblau](https://himmelblau-idm.org/) for Microsoft Entra ID
authentication and identity on Linux.

The role adds the package repository, installs the Himmelblau packages, renders
`/etc/himmelblau/himmelblau.conf`, wires NSS and PAM, masks `nscd`, and enables the
`himmelblaud` / `himmelblaud-tasks` daemons.

> ⚠️ **Lock-out risk.** This role modifies the PAM stack. Test against a VM with an
> independent root rescue session before running it on any host you cannot physically recover.

## Supported platforms

The role targets SUSE distributions first.

| Platform | Support status |
|---|---|
| SLE 16 | **Supported** — every change is integration-tested on SLE 16. |
| openSUSE Leap 16.0 | **Verified** — validated end to end; not part of continuous testing. |
| SLE 15, openSUSE Tumbleweed | **Experimental** — distribution support is present but not yet validated. |

Other distributions are not supported; the role fails with a clear error if repository, PAM, or
SSH management is enabled on them.

## Requirements

- **ansible-core >= 2.18** — the version SLES 16 ships, and the role's `min_ansible_version`.
- The `community.general` collection (see
  [`meta/collection-requirements.yml`](meta/collection-requirements.yml)).
- An Entra ID tenant **or** a standards-compliant OIDC issuer. `domain` is optional (Entra infers it
  from the first user's UPN); generic OIDC requires `himmelblau_oidc_issuer_url` **and**
  `himmelblau_app_id`. See [Generic OIDC](#generic-oidc).
- Network egress from the managed hosts to `login.microsoftonline.com` (Entra authentication) and
  `download.opensuse.org` (the `network:idm` package repository).

## Quick start

The minimal playbook — an Entra domain, login scoped to one Entra group, and local `wheel`
membership for mapped users (see [`examples/deploy.yml`](examples/deploy.yml) for a
ready-to-run version):

```yaml
---
- name: Deploy Himmelblau
  hosts: workstations
  become: true
  vars:
    himmelblau_domain: contoso.onmicrosoft.com
    himmelblau_app_id: d023f7aa-d214-4b59-911d-6074de623765
    himmelblau_pam_allow_groups:
      - f3c9a7e4-7d5a-47e8-832f-3d2d92abcd12   # "Linux Users" Entra group GUID
    himmelblau_local_groups:
      - wheel
  roles:
    - role: ansible-himmelblau
```

```bash
ansible-playbook -i inventory deploy.yml
```

On the first login (console or SSH), the user enters their UPN
(`user@contoso.onmicrosoft.com`) and completes the Entra device-code/MFA prompt. After a
successful login, a home directory is provisioned automatically, e.g.
`/home/user@contoso.onmicrosoft.com`.

## Role variables

All variables are defined in [`defaults/main.yml`](defaults/main.yml).

| Variable | Default | Description |
|---|---|---|
| `himmelblau_domain` | `""` | Entra ID domain users authenticate against. **Optional** — Entra infers it from the first user's UPN if unset. The role requires `domain`, **or** `oidc_issuer_url` when `idp_provider: generic`, unless `idp_provider: none`. Rendered only when set. |
| `himmelblau_app_id` | `""` | Entra application (client) ID for directory operations. **Required when `idp_provider: generic`** (the OIDC client id; also reused for logon-token acquisition when `logon_token_app_id` is unset). Rendered only when set. |
| `himmelblau_idp_provider` | `entra` | IdP mode: `entra` (Microsoft Entra ID) \| `generic` (sovereign OIDC via `himmelblau_oidc_issuer_url`) \| `none`. |
| `himmelblau_oidc_issuer_url` | `""` | OIDC issuer URL; rendered only when `himmelblau_idp_provider: generic`. Must **exactly** match the provider's advertised issuer (incl. path) or discovery fails. |
| `himmelblau_pam_allow_groups` | `[]` | Entra group GUIDs/UPNs allowed to log in. Empty = allow all. |
| `himmelblau_local_groups` | `[]` | Local groups mapped users are added to (e.g. `["wheel"]`). |
| `himmelblau_idmap_range` | `"200000-2000200000"` | POSIX UID/GID mapping range. |
| `himmelblau_shell` | `"/bin/bash"` | Default login shell for mapped users. |
| `himmelblau_enable_hello` | `true` | Windows-Hello PIN enrollment. For generic OIDC providers whose client app lacks refresh tokens + the `offline_access` scope, set `false` or Hello fails at login — see [Generic OIDC](#generic-oidc). |
| `himmelblau_home_attr` | `""` | Attribute that names the home dir (upstream default `uuid`). Rendered only when set. |
| `himmelblau_home_alias` | `""` | Alternative home-dir naming (upstream default `spn`). Rendered only when set. |
| `himmelblau_home_prefix` | `""` | Home-directory prefix, e.g. `/home/`. Rendered only when set. |
| `himmelblau_logon_token_app_id` | `""` | Separate app (client) ID for logon-token scopes. Rendered only when set. |
| `himmelblau_user_map_file` | `""` | Path to an external name-mapping file (the role writes the key only, not the file). Rendered only when set. |
| `himmelblau_extra_config` | `{}` | Extra `[global]` keys merged verbatim. Typed vars above win over the same key here. |
| `himmelblau_state` | `present` | `present` to deploy; `absent` to fully tear down — revert PAM/NSS, remove the config, uninstall the packages, and remove the `network:idm` repo (no orphaned references left behind). |
| `himmelblau_manage_repo` | `true` | Add the `network:idm` package repository on `present`. On `absent` the repo is removed regardless of this toggle (teardown-flag-independent). |
| `himmelblau_configure_nss` | `true` | Wire `/etc/nsswitch.conf` and mask `nscd`. |
| `himmelblau_configure_pam` | `true` | Configure the PAM stack (via `pam-config` on SUSE). |
| `himmelblau_pam_allow_no_groups` | `false` | Permit wiring PAM with no allow-group restriction (allow-all login). Leave `false` to require `himmelblau_pam_allow_groups` scoping; set `true` only to consciously accept allow-all login (admin groups do **not** satisfy the guard) — see [Before you enable PAM](#before-you-enable-pam). |
| `himmelblau_start_services` | `true` | Start (and restart on change) the `himmelblaud` daemons. Set `false` to enable-but-not-start — deploy config before an Entra tenant is reachable, or for tenant-less CI. Activation needs a working tenant. |
| `himmelblau_configure_ssh` | `false` | Opt-in: install the Himmelblau sshd config so Entra users can SSH in. Off by default (fleet lock-out vector; upstream denies SSH password-only by default — override via `password_only_remote_services_deny_list` in `extra_config`). When enabled with `start_services: true`, the role **restarts** sshd so it loads the new NSS module (a reload won't); the active connection survives (`KillMode=process`). Note: `su` to an Entra user is a known SSO limitation — use SSH/console login. |
| `himmelblau_sudo_groups` | `[]` | Entra group GUIDs whose members get sudo (rendered with `local_sudo_group` when set). |
| `himmelblau_local_sudo_group` | `"sudo"` | Local group `sudo_groups` members join (rendered only when `sudo_groups` is set). |
| `himmelblau_offline_breakglass_enabled` | `false` | Opt-in emergency offline MFA bypass; renders an `[offline_breakglass]` section when `true`. |
| `himmelblau_offline_breakglass_ttl` | `7200` | Offline break-glass TTL in seconds (used when enabled). A larger value widens the offline-authentication window — keep it as small as recovery needs allow. |
| `himmelblau_packages` | distro list | Override to pin/customize the installed packages. |
| `himmelblau_repo_url` | distro URL | Override the repository `.repo` URL. |

## Before you enable PAM

`himmelblau_configure_pam` defaults to `true`, so the role wires Himmelblau into the host PAM stack
by default. Because `himmelblau_pam_allow_groups` is the **only** key that scopes who can log in (leave
it empty and **every** Entra tenant user can authenticate), the role **refuses to configure PAM**
unless login is scoped or allow-all is explicitly accepted:

- `himmelblau_pam_allow_groups` — scope login to named Entra group GUIDs, **or**
- `himmelblau_pam_allow_no_groups: true` — consciously accept allow-all login for the whole tenant.

> **Admin groups do not scope login.** `himmelblau_local_groups` and `himmelblau_sudo_groups` only
> control local-group membership and sudo *after* a successful login — they do **not** restrict who
> can log in, so they **do not** satisfy this guard. Setting one without `himmelblau_pam_allow_groups`
> would still be an allow-all login; the role rejects that unless you opt in with
> `himmelblau_pam_allow_no_groups: true`. (Adding Himmelblau to PAM does not remove local/`files`
> auth, so root and local accounts still work — the hazard this guards against is over-permissive
> login, not lock-out.)

> **Scope only via the typed variable.** The guard reads *only* `himmelblau_pam_allow_groups`.
> Setting `pam_allow_groups` through `himmelblau_extra_config` still renders into the config, but does
> **not** satisfy the guard — the role refuses the run. Use the typed `himmelblau_pam_allow_groups`.

Keep an independent root rescue session open the first time you enrol a host, and never run PAM
changes against a machine you cannot physically recover.

## Generic OIDC

Set `himmelblau_idp_provider: generic` to authenticate against a sovereign / non-Microsoft OIDC
issuer (Keycloak, Authentik, Zitadel, …) instead of Entra. In this mode:

- **`himmelblau_oidc_issuer_url` and `himmelblau_app_id` are both required.** The issuer URL must
  match the provider's advertised issuer exactly (including any path component) or provider discovery
  fails. `app_id` is the OIDC client id.
- **`domain` is not needed** (leave it empty); the identity anchor is the issuer URL.
- **Windows Hello and `offline_access`.** `himmelblau_enable_hello` defaults to `true`. With OIDC,
  Hello enrollment requires the OIDC **client application** to allow refresh tokens and include the
  `offline_access` scope. If your client is not configured that way, set
  `himmelblau_enable_hello: false`, or Hello enrollment fails at login.

See [`examples/oidc-generic.yml`](examples/oidc-generic.yml) for a complete playbook.

## Intune MDM policy

Himmelblau can apply Microsoft Intune device-compliance policy through its `apply_policy` setting.
This role does **not** expose it as a dedicated variable and does **not** manage Intune enrollment:
enrollment and Entra **device join** happen at a user's first login — a runtime event this role does
not orchestrate, and out of scope for it. On a host that is already Entra-joined under an
Intune-**licensed** tenant with assigned policies, enable policy application through the verbatim
[`himmelblau_extra_config`](#role-variables) passthrough:

```yaml
himmelblau_extra_config:
  apply_policy: true
```

Before enabling it, note:

- **It is a no-op until the device is Entra-joined.** `apply_policy` only takes effect after a first
  successful login has joined the device; setting it on an unjoined host does nothing.
- **It requires an Intune-licensed tenant** with compliance/configuration policies assigned to the
  device — the role cannot provision or verify those.
- **It adds ~6 s of PAM login latency** while policy is applied. Leave it unset (the upstream
  default is off) unless you specifically need Intune policy applied.

## Example playbooks

The canonical minimal deployment is the [Quick start](#quick-start) playbook above. All example
playbooks live in [`examples/`](examples/):

| Playbook | Purpose |
|---|---|
| [`deploy.yml`](examples/deploy.yml) | Minimal deployment: Entra domain, login scoped to one group, `wheel` membership. |
| [`oidc-generic.yml`](examples/oidc-generic.yml) | Authenticate against a generic OIDC issuer (Keycloak, Authentik, Zitadel) instead of Entra. |
| [`sudo-and-ssh.yml`](examples/sudo-and-ssh.yml) | Grant sudo to an Entra group and enable SSH login for Entra users. |
| [`advanced-config.yml`](examples/advanced-config.yml) | Home-directory layout, login shell, idmap range, offline break-glass, repository/package overrides, and the opt-in Intune `apply_policy` passthrough. |
| [`staged-rollout.yml`](examples/staged-rollout.yml) | Stage packages and config without starting the daemons or touching PAM/NSS, for phased activation. |
| [`allow-all-login.yml`](examples/allow-all-login.yml) | Explicit allow-all login opt-in via `himmelblau_pam_allow_no_groups: true`. |
| [`teardown.yml`](examples/teardown.yml) | `himmelblau_state: absent` — reverts PAM/NSS wiring, removes the config, uninstalls the packages, removes the `network:idm` repository. |

## Idempotency and check mode

A second run of the role against an already-converged host reports zero changes. The role is
check-mode safe (`ansible-playbook --check` previews without modifying the host). Configuration
changes restart the `himmelblaud` / `himmelblaud-tasks` daemons via handlers.

## Removing Himmelblau

Set `himmelblau_state: absent` to tear the deployment down completely: the role reverts the PAM and
NSS wiring, removes `/etc/himmelblau/himmelblau.conf`, uninstalls the Himmelblau packages, and
removes the `network:idm` package repository. See
[`examples/teardown.yml`](examples/teardown.yml).

Note: on `absent`, the repository is removed regardless of the `himmelblau_manage_repo` setting —
teardown leaves no orphaned repository references behind.

## License

MIT

## Author information

Maintained by Harshvardhan Sharma
