<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Infrastructure Setup

Use the OEP CLI Installer to install or remove Deterministic Threat Detection on an existing
Ubuntu 24.04 system. For the full installer documentation, see the
[OEP CLI Installer guide](https://docs.openedgeplatform.intel.com/dev/OEP-articles/oep-cli-installer/index.html).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/open-edge-platform/edge-ai-libraries/refs/heads/release-2026.3.0/frameworks/oep-installer-cli/rendered/openedge-cli-federal-aerospace | bash -s -- install deterministic_threat_detection
```

## Remove

```bash
openedge-cli remove deterministic_threat_detection
```

## Start and Stop

To start and stop the application, see the
[README](https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/blob/release-2026.3.0/deterministic-threat-detection/README.md).
For the one-time host, TSN and switch preparation, see the
[System Requirements](./get-started/system-requirements.md).

<!--hide_directive
:::{toctree}
:hidden:

System Requirements <./get-started/system-requirements.md>

:::
hide_directive-->
