# Infrastructure Setup

There are 2 ways to prepare the required infrastructure:

1. Recommended for demo or development deployments:

   1. Deploy a clean Ubuntu OS instance.
   2. Install curl.
   3. [Install infrastructure software](./infrastructure/installation-on-ubuntu.md). The
      installer will deploy [Edge Pack](https://docs.openedgeplatform.intel.com/dev/platform-software/edge-pack/index.html),
      which ensures Intel hardware compatibility and optimization.

2. Recommended for deplyment at scale:

   1. [Create a Custom Ubuntu Image](./infrastructure/customized-image.md) with preinstalled
      infrastructure software (delivered with [Edge Pack](https://docs.openedgeplatform.intel.com/dev/platform-software/edge-pack/index.html) installation)
   2. Deploy the image across multiple computers.


The infrastructure software offers a selection of advanced options for
collecting system information and customizing performance parameters. These are documented in
[Infrastructure capabilities](./infrastructure/platform-capabilities.md).

If you have issues, see [Troubleshooting](./infrastructure/platform-capabilities.md).

<!--hide_directive
:::{toctree}
:hidden:

Installation on Ubuntu <./infrastructure/installation-on-ubuntu.md>
Customized Image <./infrastructure/customized-image.md>
Infrastructure Capabilities <./infrastructure/platform-capabilities.md>
Troubleshooting <./infrastructure/troubleshooting.md>

:::
hide_directive-->
