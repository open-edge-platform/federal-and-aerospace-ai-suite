<!--hide_directive
```{eval-rst}
.. meta::
   :description: Release notes for the deterministic threat detection subproject, covering versions 1.1.0, 1.0.1, and 1.0.0.
   :keywords: release notes, deterministic threat detection, Scenescape, Basler, Qbv, HOTA
```
hide_directive-->

# Release Notes: Deterministic Threat Detection

- [Version 1.1.0](#version-110)
- [Version 1.0.1](#version-101)
- [Version 1.0.0](#version-100)

## Version 1.1.0

**Release Date**: December 2026

**New**:

- One web dashboard for both use cases: live latency, tracking quality as Higher Order Tracking
  Accuracy (HOTA), network-load slider, Qbv toggle, system utilization, and a live architecture
  view.
- One-command deployment for four machines: `make up` / `make down`.
- Basler GigE camera support with Precision Time Protocol (PTP) hardware timestamps:
  `make up SOURCE=basler`.
- Setup scripts for the Time-Sensitive Networking (TSN) NIC, VLANs, and PTP profiles
  (`src/setup/`).

**Changed**:

- Replaced the patched Scenescape checkout with a single `gvapython` adapter in the Scenescape
  integration. The integration now uses unmodified Scenescape 2026.3 images.
- Rewrote the documentation around the new design. Removed the AXIS RTSP camera, sensor
  producer, and MQTT aggregator use case and the offline HOTA scripts.

## Version 1.0.1

**Release Date**: June 25, 2026

**New**:

- The deterministic threat detection subproject with Scenescape-specific changes
  and a use case for testing purposes.
- Documentation for setting up, configuring, and capturing HOTA metrics with
  Scenescape, both with and without traffic shaping.

**Improved**:

- Restructured the documentation to separate the Scenescape-specific
  content into its own section, while keeping the original RTSP use case
  documentation intact.

## Version 1.0.0

**Release Date**: March 25, 2026

**New**:

- Initial release of the deterministic threat detection subproject: a real-time threat detection
  system for time-sensitive networks, the code to test the use case, and documentation to set up,
  configure, and run it.
