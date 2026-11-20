<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Installation on Ubuntu

This guide installs the Handheld (Soldier System) Blueprint on an Ubuntu 24.04 target using
the [Open Edge Platform (OEP) CLI Installer](https://github.com/open-edge-platform/edge-ai-libraries/tree/main/frameworks/oep-installer-cli)
(`openedge-cli`). It is a single self-contained shell script that installs the Intel Edge Pack
components and the Federal and Aerospace handheld suite without a manual OS image build.

For the image-build and bootable-USB provisioning path instead, see
[Infrastructure Setup](infrastructure-setup.md) and [Install OEP SDKs](install-oep-sdks.md).

## Prerequisites

- Ubuntu 24.04 LTS target with Internet access (or a configured proxy).
- Sudo access on the target. The installer prompts for the sudo password unless
  `SUDO_PASSWORD` or `SUDO_ASKPASS` is set, or passwordless sudo is granted.
- See [System Requirements](infrastructure/system-requirements.md) for the minimum hardware and
  validated platforms.

## Step 1: Install the Edge Pack Components

Edge Pack provides the platform-level services (EP-IPU, EP-Manageability, and EP-TSN) that the
suite blueprint runs on. Pass `--edgepack` when installing the blueprint to install them first:

```bash
curl -fsSL https://raw.githubusercontent.com/open-edge-platform/edge-ai-libraries/refs/heads/main/frameworks/oep-installer-cli/rendered/openedge-cli > /tmp/openedge-cli
sudo chmod +x /tmp/openedge-cli
sudo mv /tmp/openedge-cli /usr/bin
openedge-cli install handheld_blueprint --edgepack
```

After the first invocation, the installer saves itself under `/usr/bin/openedge-cli`, so
subsequent commands can call `openedge-cli` directly instead of piping from `curl`.

During installation, system might reboot. After it is back online, follow instructions from installer to resume installation. If system didn't reboot, go to next step.

## Step 2: Install the Handheld Suite

Install the full Federal and Aerospace handheld profile, which includes the handheld platform,
application and required drivers and models.

```bash
openedge-cli install federal_and_aerospace_ai_suite_handheld
```

To install an individual component instead of the full profile, for example the handheld
application only:

```bash
openedge-cli install handheld_multi_modal
```

## Step 3: Start the Application

Profiles cannot be started as a group; start the individual component:

```bash
openedge-cli start handheld_multi_modal
```

Stop it with:

```bash
openedge-cli stop handheld_multi_modal
```

## Step 4: Validate the Installation

Continue with [Access Application User Interface](access-application.md) to open the operator
console.

## Removing Components

Remove a profile or a component. This does not remove dependency items such as GPU/NPU drivers
installed by `--edgepack`; pass `--remove-all` to force removing everything:

```bash
openedge-cli remove federal_and_aerospace_ai_suite_handheld
openedge-cli remove federal_and_aerospace_ai_suite_handheld --remove-all
```

## Related Guides

- [OEP CLI Installer README](https://github.com/open-edge-platform/edge-ai-libraries/blob/main/frameworks/oep-installer-cli/README.md) — full command reference, options, and credentials handling.
- [Infrastructure Setup](infrastructure-setup.md) — OS image build and bootable-USB provisioning path.
- [Install OEP SDKs](install-oep-sdks.md) — verify hardware accelerators on a provisioned target.
- [Install Handheld Multi-Modal Application](deploy-applications.md) — manual `docker compose` deployment path.
