# Create VLANs on All Machines

This guide explains how to create the VLAN interfaces on the TSN network card of each machine, either automatically with a script or manually.

The demo uses three VLANs on the TSN NIC (`tsn0`):

| VLAN | Subnet | Priority (PCP) | Carries |
| ------ | -------- | ---------------- | --------- |
| 1 | `192.168.127.x` | 1 | Camera data (RTSP and MQTT) and switch management |
| 3 | `192.168.3.x` | 3 | Basler cameras (Basler test only) |
| 5 | `192.168.5.x` | 5 | Background load |

## Automatic

Run `setup_tsn_nic.sh` once per machine; see [First-time setup](../../first-time-setup.md#2-nic-and-vlans-every-machine).
It renames the NIC to `tsn0`, creates `tsn0.1`, `tsn0.3` and `tsn0.5` with the address `192.168.<vlan>.<id>`, and maps every
frame priority to PCP = VLAN ID. Without the map, all frames leave with priority 0 and the switch
cannot tell the traffic classes apart.

## Manual (one VLAN)

```bash
sudo ip link add link tsn0 name tsn0.1 type vlan id 1
sudo ip link set tsn0.1 type vlan egress-qos-map 0:1 1:1 2:1 3:1 4:1 5:1 6:1 7:1
sudo ip addr add 192.168.127.11/24 dev tsn0.1
sudo ip link set tsn0.1 up
```

Repeat for VLANs 3 and 5 with the matching ID and priority. Then, assign the VLANs on the switch, following the
[Configure VLANs on the Moxa switch](./configure-vlan-on-moxa-switch.md) guide.
