<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Handheld (Soldier System) Blueprint

<!--hide_directive
<div class="component_card_widget">
  <a class="icon_github" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/tree/main/handheld-multi-modal">
     GitHub
  </a>
  <a class="icon_document" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/blob/main/handheld-multi-modal/README.md">
     Readme
  </a>
  <a class="icon_download" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/releases/download/fedaero-latest/handheld-multi-modal.zip">
     Download Package
  </a>
</div>
hide_directive-->

The Handheld Blueprint provides edge node infrastructure software enabling efficient and robust
operations under difficult field conditions. The edge computing platform enables hardware
acceleration capabilities, optimized for Intel® edge hardware.
On top of the system layer, it offers AI-enabled reference applications for handheld deployment
scenarios, making it easy to demonstrate the solution and develop custom software.

The main application offered is [Handheld Multi-Modal](./multi-modal/index.md), a
multi-modal AI operator console that runs entirely on the device. See
[Reference Applications](./applications.md) for all available applications.


## Deployment and Usage

Follow these steps to deploy the Handheld (Soldier System) Blueprint:

1. [Install on Ubuntu](./infrastructure/installation-on-ubuntu.md) or [Customized Image](./infrastructure/customized-image.md) — Build the OS image, flash it to a bootable USB, and validate the provisioned platform.
2. [Reference Applications](applications.md) — Deploy and use the Handheld Multi-Modal Application or other applications.
3. [Benchmarks](benchmarks.md) — Benchmark AI workloads across the available hardware.


<!-- 4. [Install OEP SDKs](install-oep-sdks.md) (optional) — Verify hardware accelerators and install the OEP Vision AI SDK on the provisioned target. -->

## AI Agent SKILLs

The Handheld Blueprint supports AI agent skills for GitHub Copilot and Claude Code, covering
both platform-level automation (image build, provisioning, power and thermal tuning) and
application-level pipeline generation with Intel DL Streamer. See
[AI Agent SKILLs](agents.md) for the available skills and how to use them.

<!--hide_directive
:::{toctree}
:hidden:

Infrastructure Setup <infrastructure-setup.md>
Reference Applications <applications.md>
Benchmarks <benchmarks.md>
AI Agent SKILLs <agents.md>
Release Notes <release-notes.md>

:::
hide_directive-->
