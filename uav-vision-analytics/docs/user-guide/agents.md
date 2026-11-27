# Agent SKILLs

This section covers the AI agent skills and coding-agent workflows available for the Uncrewed
Aerial Vehicle (UAV) Blueprint — from platform-level automation (image build, provisioning,
power and thermal tuning) to application-level pipeline generation with Intel DL Streamer.

- [DL Streamer Pipelines Guide](infrastructure/build-dlstreamer-pipelines.md) — Building,
  running, and troubleshooting DL Streamer video analytics pipelines, including AI-assisted
  pipeline generation with the DL Streamer Coding Agent.
- [Infrastructure AI Agent Integration](infrastructure/agent-skills.md) — Available
  agent skills for building images, provisioning, and power/thermal tuning, and how to run them
  from a developer host or directly on a provisioned target.
- [SDK Agent Commands and MCP Tools](infrastructure/uav-sdk-apps-skill.md) — Claude Code
  slash commands that drive the UAV Mission Compute SDK stack (start, validate, capture,
  switch camera, cleanup), plus the MCP server tools exposing Anomalib, DL Streamer,
  Edge AI Suites, and live MAVLink telemetry.
- [Vision Analytics applicatioon skills](https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/tree/release-2026.3.0/uav-vision-analytics/.github/skills)
  for setting up the applications and the Open Edge Platform microservices.
- [Ground Station applicatioon skills](https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/blob/release-2026.3.0/uav-ground-station/.github/skills/uav-ground-station/SKILL.md)
  for setting up the applications and the Open Edge Platform microservices.


<!--hide_directive
:::{toctree}
:hidden:

DL Streamer Pipelines Guide <infrastructure/build-dlstreamer-pipelines.md>
Infrastructure AI Agent Integration <infrastructure/agent-skills.md>
SDK Agent Commands and MCP Tools <infrastructure/uav-sdk-apps-skill.md>
Vision Analytics skills <https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/tree/release-2026.3.0/uav-vision-analytics/.github/skills>
Ground Station skills <https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/blob/release-2026.3.0/uav-ground-station/.github/skills/uav-ground-station/SKILL.md>

:::
hide_directive-->
