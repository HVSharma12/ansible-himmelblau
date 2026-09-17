# Changelog

All notable changes to this role are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the role adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.1] - 2026-09-18

### Added
- Integration tests for behaviour that previously had none: the supported-platform contract (the
  SL-Micro/Immutable variant is admitted, and the SAP variant is refused), the fail-loud refusals
  when PAM or SSH enrolment cannot be wired on a platform, the staged rollout
  (`himmelblau_configure_nss` / `himmelblau_configure_pam` set to `false` install and render but
  wire nothing), check-mode safety on a converged host, the `tss` group the daemon's unit requires,
  and a converge under a play with `gather_facts: false`. The existing check that a pre-16.1 host is
  refused moved into the same file, so the transactional-update test now covers the reboot contract
  alone.

### Fixed
- A dry run (`ansible-playbook --check`) on a host the role had never converged failed at the
  `Restart himmelblau` handler with `Could not find the requested service himmelblaud`, and so did
  a real converge on a transactional host with `himmelblau_transactional_update_reboot_ok: false`
  and the daemons at their default `himmelblau_start_services: true`: the handler restarted units
  that did not exist yet (never installed by the dry run, or staged but not live until the reboot).
  It now restarts only units that exist, exactly as the service-management task already did. A
  plain converge is unchanged, and a dry run on an already-converged host still previews the
  restart. The suite runs this dry run inside the test VM.
- `tox.ini` declared `lsr_enable` in the wrong section, so the tox-lsr plugin was never enabled and
  the integration command the file and README documented resolved no environment. The setting has
  moved to `[lsr_config]`, `yamllint` now runs against the repo's own `.yamllint.yml`, and the
  documented command names the image and the playbooks that `runqemu` requires. `tox -e
  black,yamllint` now passes — the PAM login probe was not formatted the way the `black` environment
  expects — and `tox.ini` records that the `ansible-lint` environment additionally needs `yq` on
  `PATH`, which tox-lsr's helper shells out to. The `commit_skip` setting is gone: no version of
  tox-lsr reads it, so it never had the effect its comment claimed.
- Every `tests/tests_*.yml` now converges the state it needs itself instead of assuming a freshly
  booted host. Passing several test playbooks to one `tox` invocation runs them in a single VM, and
  the transactional-update test previously depended on an earlier test having removed the packages.

## [1.2.0] - 2026-09-04

### Added
- Transactional-update support (SLE 16.1 Immutable): the role detects transactional systems and
  follows the Linux System Roles reboot contract via the new
  `himmelblau_transactional_update_reboot_ok` variable — `true` reboots the host to apply a staged
  package transaction, `false` notifies and continues, unset fails so the reboot requirement is
  not overlooked.

### Changed
- **BREAKING — SLE 16.1 is now the only supported platform.** Himmelblau ships in the SLE 16.1
  base product, so the role installs from there and no longer adds the third-party `network:idm`
  repository. The managed hosts must already be registered with the SUSE Customer Center (or an
  RMT/SMT mirror). SLE 15.x, SLE 16.0, openSUSE Leap and Tumbleweed carry Himmelblau only in
  `network:idm` and are **no longer supported** — stay on the `v1.x` series for those, noting the
  login-scoping defect recorded under Security below, which v1.x carries.
- Published under the SUSE organisation: the role's Galaxy name in `meta/main.yml` is now
  `suse.himmelblau` (namespace `suse`; author and company SUSE). Installed from git as the README
  describes, the role is still referenced as `ansible-himmelblau`.
- Generic OIDC documentation corrected from a live Keycloak login: the `offline_access` scope is a
  prerequisite of the login itself (Himmelblau's device flow always requests it), not only of
  Windows Hello. No behaviour change.
- **Documentation corrections from the Himmelblau maintainer's review.** Several statements were
  wrong and are fixed: `himmelblau_domain` is **required** for Entra (Himmelblau does *not* infer it
  from the first user's UPN) and optional only when authenticating via OIDC; `himmelblau_app_id` is
  almost never needed for Entra — only for specific cases such as enumerating groups or reading
  extended attributes — so it is no longer in the Quick start or `examples/deploy.yml`; and
  `himmelblau_pam_allow_groups` **does** apply to OIDC group and role claims (Himmelblau 4.0+;
  earlier builds carry no OIDC group claims, so list users there).

### Removed
- **BREAKING — `himmelblau_idp_provider` is removed.** It was a role invention: Himmelblau has no
  such setting and derives the mode from `oidc_issuer_url` alone. The role now does the same —
  set `himmelblau_oidc_issuer_url` (with `himmelblau_app_id`) for generic OIDC, leave it empty for
  Entra. **Migration:** delete `himmelblau_idp_provider` from your playbooks; `generic` needs no
  replacement beyond the issuer you already set, and `entra` was the default. The former
  `himmelblau_idp_provider: none` — the only mode that waived the identity anchor — has no
  replacement: a config with neither `himmelblau_domain` nor `himmelblau_oidc_issuer_url` cannot
  authenticate anyone, and the role now refuses it. **One case changes behaviour silently:** if a
  playbook set `himmelblau_oidc_issuer_url` while leaving `himmelblau_idp_provider` at its `entra`
  default, the issuer was previously rendered nowhere and ignored. It now selects OIDC on its own —
  **clear the issuer** to stay on Entra. (Such a playbook also needs `himmelblau_app_id`, so it
  fails the pre-flight assert rather than silently switching provider mid-converge.)
- **BREAKING — the repository variables and tasks are removed.** `himmelblau_manage_repo`,
  `himmelblau_repo_url`, and the repository add/remove tasks are gone; there is no repository for
  the role to manage, and no mirror knob — package sourcing follows the host's registration.
- Teardown no longer removes a repository, because it never adds one. Note for hosts wired by the
  v1.x series: the `network:idm` repository v1.x added is therefore not removed by this version's
  teardown — unwind it with v1.x or remove it manually.

### Security
- **Login scoping could be bypassed on Himmelblau >= 3.1.8 (SLE 16.1 ships 3.1.11).** Every
  earlier release of this role (v1.0.0 and v1.1.0) set the Himmelblau
  `account` line to `sufficient`; once Himmelblau began serving synthetic shadow entries,
  `pam_unix` no longer refused Entra ID users, so a user **outside** `himmelblau_pam_allow_groups`
  who authenticated successfully was let in. This release writes the control Himmelblau itself
  declares, `[success=ok auth_err=die default=ignore]`, which denies out-of-group users terminally
  and leaves local users on `pam_unix`. **Remedy:** on SLE 16.1 hosts, re-run this release — it
  repairs the line automatically. On hosts this release refuses to run on (SLE 15.x, SLE 16.0,
  openSUSE — the v1.x platforms), **check the installed version first with `rpm -q himmelblau`:**
  - **3.1.8 or later** — the bypass applies. Regenerate the safe line with
    `pam-config --add --himmelblau` (it writes `required`, which also denies out-of-group users),
    and do not run a v1.x release against the host again, because its PAM step re-applies
    `sufficient`.
  - **Older than 3.1.8** — the bypass does **not** apply: without synthetic shadow entries
    `pam_unix` already refuses the out-of-group user, which is why v1.x used `sufficient` there.
    **Do not apply `required` or `[success=ok auth_err=die default=ignore]` on these hosts** — with
    no shadow entry the following `account required pam_unix.so` returns `PAM_AUTHINFO_UNAVAIL` and
    the account phase fails for **every** Entra user, in-group included, over console, `su` and
    SSH alike.

---

Releases 1.0.0 and 1.1.0 predate this public repository and are not documented here.
