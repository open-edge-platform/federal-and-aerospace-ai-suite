<!--hide_directive
```{eval-rst}
.. meta::
   :description: Synchronize the machines and the Moxa switch with the IEEE 802.1AS (gPTP) Precision Time Protocol (PTP) profile.
   :keywords: PTP, gPTP, IEEE 802.1AS, Moxa, grandmaster, ptp4l, phc2sys
```
hide_directive-->

# Configure Precision Time Protocol (PTP), IEEE 802.1AS (gPTP)

This guide explains how to synchronize the machines and the switch with the IEEE 802.1AS (gPTP)
profile. The switch acts as the PTP grandmaster. Each machine runs `ptp4l` to synchronize the
NIC clock and `phc2sys` to synchronize the system clock. gPTP is one of two supported profiles; the
other is [IEEE 1588v2](./configure-ptp-1588v2.md), which the Basler cameras require. A port can run
only one profile at a time, so make sure that the switch and **all** machines use the same one.

## Machines

Run `ptp-install.sh` once during the
[First-time setup](../../first-time-setup.md#3-ptp-every-machine).
Then switch the profile with:

```bash
sudo ptp-profile gptp
sudo ptp-profile status
```

Equivalent manual commands (`ptp-install.sh` creates `/etc/linuxptp/gPTP.cfg`):

```bash
sudo ptp4l -i tsn0 -f /etc/linuxptp/gPTP.cfg --step_threshold=1 -m -s
sudo phc2sys -s tsn0 -c CLOCK_REALTIME --step_threshold=1 --transportSpecific=1 -w -m
```

`phc2sys` steps `CLOCK_REALTIME`, so NTP clients (`chrony`, `systemd-timesyncd`) must be off.
`ptp-install.sh` disables them.

## Switch

Set the profile in the web interface (System > Time > Time Synchronization) or with
`python3 ptp_profile.py 802.1as` from `src/switch/` on a machine that reaches the switch
(`python3 ptp_profile.py --help` lists the options).

## Verify

`phc2sys` should report an offset in the tens of nanoseconds:

```text
phc2sys[1234.567]: CLOCK_REALTIME phc offset 12 s2 freq +0 delay 512
```
