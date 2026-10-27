<!-- Template: feature_request.yml. Dropdowns: Harness = Not applicable;
Platform = macOS, Linux; Harness mode = Not applicable; Expected reach = Some users;
Authentication type = Not authentication-related. -->

# [Feature] Drain a host and let the server request host upgrades

## Problem or use case

We run a self-hosted server with several hosts, each installed as a user service
with `omnigent host enable`. Rolling out a new build means a shell on every
machine and an `omnigent upgrade` on each, and a host restart can end turns that
are running. #10672 describes the same cost: every mid-turn "Runner process
terminated" failure in its 7-day sample was a host that was stopped and replaced
by a newer build.

Several pieces are open or in flight:

- #8955 (#8868): `omnigent upgrade` restarts an enabled host service.
- #10673 (#10672): `host enable` waits for running turns before replacing a host.
- #8164 (#8155): concurrent installer runs on one shared install.
- #10872 (#10377): resume interrupted top-level sessions after a host restart,
  for managed sandbox hosts.

Two gaps remain:

1. **A host can't be told to stop taking new work.** Stopping it terminates its
   runners (`_cleanup_runners`, `omnigent/host/connect.py:4412`). Waiting for
   turns happens only in the CLI, which polls session status
   (`_wait_for_local_sessions_to_drain`, `omnigent/cli.py:5361`), and new turns
   can still start while it waits.
2. **The server can't ask a host to update.** It knows each host's version from
   the hello frame, but acting on it needs a shell on each machine.

## Proposed solution

Three stages, each useful on its own:

1. **Host drain mode.** `omnigent host drain [--deadline N]`, plus a `host.drain`
   frame behind a new capability token. A draining host refuses new runner
   launches with a retryable error, lets running turns finish (up to the
   deadline), then exits with a status its service manager restarts on. The
   systemd unit currently sets `RestartPreventExitStatus=78 143`
   (`omnigent/host/service.py:135`), so this needs a distinct exit code. For new
   turns the server treats a draining host as offline, so messages take the
   existing paths: #9020's reconnect grace, then #10666's `host_offline` refusal
   that the web holds as "Waiting for host". Drain adds no hold of its own.
2. **Server-requested upgrade.** `POST /v1/hosts/{host_id}/upgrade` with a target
   version, sending a `host.upgrade` frame, modelled on the harness install
   frame (`HostInstallHarnessFrame`,
   `POST /v1/hosts/{host_id}/harnesses/{harness}/install`). The host drains, then
   a detached process runs the existing `omnigent upgrade --target-version` path
   (with #8955's service restart), and the host reconnects on the new build.
   The server names only a version; the host installs from its own configured
   index, never from a server-supplied URL or script. Hosts without the
   capability are skipped. Host owners and admins only.
3. **Opt-in policy and UI.** A per-host setting: off (default), manual (an
   Update button in the hosts list), or follow the server's version.
   Externally managed installs (#10197) never self-upgrade. The hosts list shows
   each host's version next to the server's.

What a restart costs depends on two other changes:

- **Running turns:** #10872. Self-hosted hosts reconnect by themselves, so they
  need only its top-level resume, not the wake sweep. Could its policy cover
  them as well (#8744)?
- **Messages sent during the restart:** #10666 holds them in the window that
  sent them, so they are lost if that window closes, and Slack/API sends still
  fail. An upgrade that follows the server, possibly overnight, is when no
  window is open. A server-owned queue (#10986) would keep these on the server.

Out of scope: upgrading the server itself, which belongs to the deployment.

Questions:

- Is a server-requested upgrade a direction you want, or should a host only ever
  be upgraded from its own machine? @yaoharry, you closed #8075 (daily idle
  restart) and #9646 (daily upgrade). What made you drop them, so this avoids
  the same problems?
- Would you take stage 1 (drain mode) on its own first?

We can implement this in stages.

## Alternatives considered

- **A timer on each host** that runs `omnigent upgrade` when the host is idle.
  This works once #8955 lands and is what we will run meanwhile, but a turn can
  start between the idle check and the stop, and there's no central view of
  which host runs which build.
- **A scheduled daily restart or upgrade** (#8075, #9646). #8075 restarted only
  while idle, but its review found that the idle check could pass during a
  reconnect; #9646 restarted regardless of running turns. Drain mode makes the
  host itself refuse new work, which closes that gap.
- **A host `--auto-upgrade` flag** that follows the server's build by running the
  server's install script (seen in #8155, not upstream). Hosts follow the server,
  but they run a server-supplied script, and two hosts sharing one install
  corrupted it.
