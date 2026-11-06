<!--hide_directive
```{eval-rst}
.. meta::
   :description: Learn how a Time-Sensitive Networking (TSN) switch keeps AI video workloads deterministic while the network is flooded with background traffic.
   :keywords: deterministic threat detection, Time-Sensitive Networking, TSN, IEEE 802.1Qbv, Time-Aware Shaper, Scenescape, MQTT, latency, HOTA
```
hide_directive-->

# Deterministic Threat Detection with Time-Sensitive Networking (TSN) - Preview

<!--hide_directive
<div class="component_card_widget">
  <a class="icon_github" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/tree/main/deterministic-threat-detection">
     GitHub
  </a>
  <a class="icon_document" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/blob/main/deterministic-threat-detection/README.md">
     Readme
  </a>
  <a class="icon_download" href="https://github.com/open-edge-platform/federal-and-aerospace-ai-suite/releases/download/fedaero-latest/deterministic-threat-detection.zip">
     Download Package
  </a>
</div>
hide_directive-->

The Deterministic Threat Detection application shows how a TSN switch keeps AI video
workloads deterministic while the network is flooded with background traffic.
The application uses an IEEE 802.1Qbv Time-Aware Shaper (TAS), which confines the background
load to its own time slot, so the camera traffic keeps its low latency and the tracking
quality remains stable.
The application provides one web dashboard that you use to run two use cases:

| Use case         | What it shows                                                  | Metric                                                                                          |
| ---------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **1 - Latency**  | Two cameras run AI inference and publish the results over MQTT | One-way network latency per message                                                             |
| **2 - Tracking** | Scenescape fuses two camera views into tracked people          | Live Higher Order Tracking Accuracy (HOTA) score (test videos) or tracker rate (Basler cameras) |

A slider injects User Datagram Protocol (UDP) load of up to 1 Gbit/s from a fourth machine.
A toggle enables the TAS on the switch. With the shaper off, the load starves both use cases;
with it on, they are unaffected.

![Dashboard: use case 1](./_assets/uc1-latency.gif)

![Dashboard: use case 2](./_assets/uc2-tracking-video.gif)

## Learn More

- [System requirements](./system-requirements.md)
- [First-time setup](./first-time-setup.md)
- [Get started](./get-started.md)
- [How-to guides](./how-to-guides.md)
- [Release notes](./release-notes.md)

<!--hide_directive
:::{toctree}
:hidden:

system-requirements
first-time-setup
get-started
how-to-guides
Release Notes <./release-notes.md>

:::
hide_directive-->
