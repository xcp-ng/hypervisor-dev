# Introduction

This document present an analysis of what out-of-tree kernel drivers would
be needed for our XCP-ng v9 release.  The list of out-of-tree drivers is
taken from XenServer 9, and for each, I've looked:

 - if there exists a version of the driver directly in the kernel drivers sources
   - if yes:
     - is it enabled in our dom0 kernel config?
	 - what are the main differences between the driver in our dom0 versus the XenServer dom0?
	 - recommendation on whether to enable in the config or ship as an out-of-tree kernel module.
   - if not:
     - Ship it as an out-of-tree drivers

## Summary

In-tree versions are from v6.12.115. "Optional OOT" means shipping the
out-of-tree module as a non-default driver, only for the listed use case.

| Driver             | XS version          | In-tree (6.12) | Recommendation                    | Optional OOT only for                          | Notes                                |
|--------------------|---------------------|----------------|-----------------------------------|------------------------------------------------|--------------------------------------|
| avago-megaraid-sas | 07.737.03.00        | 07.727.03.00   | In-tree only                      | -                                              | backport upstream fixes if needed    |
| avago-mpt3sas      | 57.00.01.00         | 48.100.00.00   | In-tree default + optional OOT    | SAS3716, PEX88000, CSMI tooling                | -                                    |
| broadcom-bnxt-en   | 1.10.3_239.1.68.0   | yes (no ver.)  | In-tree default + optional OOT    | Thor3 (BCM577xx)                               | -                                    |
| broadcom-mpi3mr    | 8.17.1.0.0          | 8.12.0.0.50    | In-tree only                      | -                                              | backport upstream fixes if needed    |
| cisco-enic         | 4.11.0.97           | yes (no ver.)  | In-tree default + optional OOT    | SR-IOV (PF VF creation, V2 VFs), PTP, XDP      | -                                    |
| cisco-fnic         | 2.0.0.116           | 1.7.0.1        | In-tree default + optional OOT    | FC-NVMe                                        | -                                    |
| emulex-lpfc        | 14.4.725.6          | 14.4.0.5       | In-tree default + optional OOT    | LPe38104S (G7S), FC-SP auth                    | OOT drops pre-G6 HBAs                |
| intel-i40e         | 2.28.16             | yes (no ver.)  | In-tree default + optional OOT    | VF-d sysfs, extra VF private flags             | port XS PTP work queue fix           |
| intel-ice          | 2.6.4               | yes (no ver.)  | In-tree default + optional OOT    | E835, VF ADQ, VF live migration                | port XS SR-IOV/Xen fix, ship DDP pkg |
| intel-igb          | 5.17.5              | yes (no ver.)  | In-tree only                      | -                                              | -                                    |
| intel-ixgbe        | 6.1.5               | yes (no ver.)  | In-tree default + optional OOT    | E610, X550EM_A QSFP                            | port XS order-1 RX buffer fix        |
| qlogic-qla2xxx     | 10.02.15.00_k       | 10.02.09.300-k | In-tree default + optional OOT    | SAN congestion management, virtual lanes       | OOT drops 8xxx CNAs and target mode  |

## Drivers

The list of out-of-tree drivers was extracted from the XenServer Sources
iso.

### avago-megaraid-sas

Version: 07.737.03.00-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_MEGARAID_NEWGEN=y
CONFIG_MEGARAID_MM=m
CONFIG_MEGARAID_MAILBOX=m
CONFIG_MEGARAID_LEGACY=m
CONFIG_MEGARAID_SAS=m
```
Version in-tree:
 - 6.6: 07.725.01.00-rc1
 - 6.12: 07.727.03.00-rc1
 - (7.2: 07.734.00.00-rc1)

Main differences other than bug-fixes between the two upstream in-tree versions:
  - nothing notable (cleanups, flexible arrays, no more `QUEUE_FLAG_NOMERGES`)

Not much difference between upstream and out-of-tree a part from compatibility code.

#### Recommendation

No need to ship the out-of-tree driver as we have `CONFIG_MEGARAID_SAS=m`
in-tree and it supports the same hardware.

### avago-mpt3sas

Version: 57.00.01.00-9.2
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_SCSI_MPT3SAS=m
CONFIG_SCSI_MPT3SAS_MAX_SGE=128
```
Version in-tree:
 - 6.6: 43.100.00.00
 - 6.12: 48.100.00.00

Main differences other than bug-fixes between the two upstream in-tree versions:
  - support for 22.5 Gbps SAS link rate
  - support firmware update without rebooting HBA

Main differences between in-tree v6.12.115 and out-of-tree:
   - SAS3716 (0x00D0) and PEX88000 / Atlas PCIe switch (0x00B2) support which in-tree doesn't have
   - SAS3508 (0x00AD) and SAS3516 (0x00AA) not supported by out-of-tree but is in-tree
   - MCTP passthrough ioctl (upstream in 6.13)
   - CSMI ioctl interface, used by some legacy HPE/vendor management tools

#### Recommendation

Keep `CONFIG_SCSI_MPT3SAS=m` in-tree as the default; it supports all the
mainstream SAS3008/3108/34xx/35xx/38xx/39xx HBAs and we can ship the
out-of-tree module as an optional (non-default) driver only if we need
SAS3716 / Atlas PEX88000 support or customers hit compatibility issues.

### broadcom-bnxt-en

Version: 1.10.3_239.1.68.0-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_BNXT=m
CONFIG_BNXT_SRIOV=y
CONFIG_BNXT_FLOWER_OFFLOAD=y
CONFIG_BNXT_DCB=y
CONFIG_BNXT_HWMON=y
# CONFIG_INFINIBAND_BNXT_RE is not set
```
Version in-tree (no driver version upstream, firmware interface version):
 - 6.6: HWRM 1.10.2.118
 - 6.12: HWRM 1.10.3.85
 - out-of-tree: HWRM 1.10.3.180

Main differences other than bug-fixes between the two upstream in-tree versions:
  - BCM5760X (Thor2, up to 400G) support, including VFs and PTP
  - dynamic MSI-X, crash dump via ethtool, RSS contexts, per-queue stats

Main differences between in-tree v6.12.115 and out-of-tree:
   - Thor3 BCM57700 (0x1770), BCM57708 (0x1778) and P8 VF (0x1820) support
     added in out-of-tree.

   - BCM58808 (0x16f0) and Stingray SoC BCM5880x (0xd800/0xd802/0xd804) not
     supported by out-of-tree but is in-tree (ARM SmartNIC SoCs, so we
     probably don't care?)
   - TruFlow / custom flower offload engine (`tf_core`, `tfc_v3`, `tf_ulp`)
   - kTLS/QUIC crypto offload (unusable for us: `CONFIG_TLS_DEVICE` is off)
   - RoCE-related extras (UDCC, DCQCN) and a larger ULP interface for
     Broadcom's out-of-tree `bnxt_re` (we don't build `bnxt_re`)
   - fwctl (`CONFIG_FWCTL` is off), LFC ioctl, AF_XDP zero-copy, netmap,
     doorbell recovery (HDBR)

#### Recommendation

Keep `CONFIG_BNXT=m` in-tree as the default; it supports all the
BCM573xx/574xx/575xx/5760X NICs. Ship the out-of-tree module as an optional
(non-default) driver only if we need Thor3 (BCM577xx) support or customers
hit compatibility issues / require the customer flower offload engine.

### broadcom-mpi3mr

Version: 8.17.1.0.0-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_SCSI_MPI3MR=m
```
Version in-tree:
 - 6.6: 8.5.0.0.0
 - 6.12: 8.12.0.0.50
 - (7.2: 8.17.0.3.50, very close to the out-of-tree version)

Main differences other than bug-fixes between the two upstream in-tree versions:
  - SAS5116 (0x00b3/0x00b5) support
  - PCI error recovery (AER) handlers
  - host diag buffer / trigger support and the matching ioctls

Main differences between in-tree v6.12.115 and out-of-tree:
   - MPI3 headers 3.0.39 vs 3.0.34 in-tree (upstream at 3.0.39 in 7.2)
   - segmented hardware trace buffer, task abort error handling, IOC
     shutdown retry, queue-full tracking (all upstream by 7.2)
   - different module parameters:
     - out-of-tree replaces `prot_mask`/`prot_guard_mask` with
       `enable_dif` (default 1) and `enable_dix` (default 0). This matches
       in-tree default (`prot_mask=0x07`, DIX off)
     - out-of-tree only: `drv_db_level`, `enable_segqueue`,
       `tm_failure_reset` (`threaded_isr_poll` is upstream in 7.2)

#### Recommendation

Keep `CONFIG_SCSI_MPI3MR=m` in-tree; it supports the same hardware. The
out-of-tree driver only brings fixes and a few features that are all
upstream by 7.2, so we don't need to ship it. If needed, backport the
relevant upstream fixes to our 6.12 kernel instead.

### cisco-enic

Version: 4.11.0.97-9.2
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_ENIC=m
```
Version in-tree: none (`DRV_VERSION` was dropped upstream).

Main differences other than bug-fixes between the two upstream in-tree versions:
  - per-queue statistics (ethtool and netdev qstats)
  - ethtool get_channels support

Main differences between in-tree v6.12.115 and out-of-tree:
   - SR-IOV V2 VF (0x02b7) support which in-tree doesn't have (device ID
     and VF type detection upstream in 7.1)
   - SR-IOV PF support: VF creation (`sriov_configure`) and PF/VF mailbox
     (`enic_mbox*.c`, `enic_sriov.c`). Not upstream, even in 7.2, which
     only has the first admin channel / resource discovery patches
   - PTP hardware clock (`enic_clock.c`) and XDP (`enic_xdp.c`), not upstream
   - extra module parameters: `rxcopybreak` (removed upstream in 6.15 when
     enic switched to page pool), `enic_dev_close_wait`

#### Recommendation

Keep `CONFIG_ENIC=m` in-tree as the default; it supports all VIC adapters
as regular NICs. Ship the out-of-tree module as an optional (non-default)
driver only if we need SR-IOV on Cisco VIC (creating VFs from dom0 or V2
VFs), PTP or XDP, which in-tree can't provide.

### cisco-fnic

Version: 2.0.0.116-9.1
Variant generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_FCOE_FNIC=m
CONFIG_LIBFC=m
CONFIG_LIBFCOE=m
```
Version in-tree:
 - 6.6: 1.6.0.57
 - 6.12: 1.7.0.1
 - (7.2: 1.9.0.1)

Main differences other than bug-fixes between the two upstream in-tree versions:
  - multiqueue (MQ) I/O support

Main differences between in-tree v6.12.115 and out-of-tree:
   - same PCI ID (0x0045 only)
   - out-of-tree does its own fabric discovery (FDLS, FIP, FDMI) instead of
     using libfc/libfcoe. Upstream switched to FDLS in 6.14, so the 6.12
     in-tree driver is still the old libfc-based design
   - FC-NVMe initiator support (`fnic_nvme.c`), not upstream even in 7.2
   - port channel RSCN handling (upstream 6.14+)
   - vendor-only: ioctl char devices (`fnic_ioctl.c`), procfs entries
   - extra module parameters: `fnic_fdmi_support`, `fnic_tgt_id_binding`,
     `pc_rscn_handling_feature_flag` (upstream 6.14+), and out-of-tree only
     `fnic_max_lun`, `dev_loss_tmo`, `fnic_tweaks`, `fnic_dev_close_wait`,
     `fnic_wqerr_debug`, `nvme_max_ios_to_process`

#### Recommendation

Keep `CONFIG_FCOE_FNIC=m` in-tree as the default; it supports the same
hardware for FCoE/SCSI. Ship the out-of-tree module as an optional
(non-default) driver only if we need FC-NVMe over Cisco VIC, which in-tree
can't provide. Note that the 6.12 in-tree driver is on the old libfc design
Cisco has moved away from, so FDLS-specific fixes from Cisco won't
backport easily.

### emulex-lpfc

Version: 14.4.725.6-2
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_SCSI_LPFC=m
CONFIG_SCSI_LPFC_DEBUG_FS=y
```
Version in-tree:
 - 6.6: 14.2.0.14
 - 6.12: 14.4.0.5
 - (7.2: 15.0.0.0)

Main differences other than bug-fixes between the two upstream in-tree versions:
  - 32 byte CDB support
  - VMID loopback tests, NVMe target `host_traddr`

Main differences between in-tree v6.12.115 and out-of-tree:
   - LPe38104S / Lancer G7S (0xf600) support which in-tree doesn't have
     (still not upstream in 7.2)
   - out-of-tree only supports Lancer G6, G7, G7P and G7S (LPe31000/32000,
     LPe35000, LPe36000, LPe38104S). All the older HBAs (LPe12000/16000,
     Lancer G5 and older, Skyhawk/OCe14000 FCoE, ...) are supported in-tree
     only
   - LPe42100 / Lancer G8 (0xd300) and 128G link speed: not in 6.12 nor in
     out-of-tree, upstream in 7.1
   - FC-SP-2 DH-CHAP authentication (`lpfc_auth.c`, `lpfc_enable_auth`),
     not upstream
   - extra module parameters: `aer_support`, `enable_e2e`,
     `enable_fcp_priority`, `enable_scsi_mq`, `external_dif`,
     `lpfc_enable_auth`, `throttle_log_cnt`, `throttle_log_time`;
     `lun_queue_depth` renamed `lpfc_lun_queue_depth`; no `enable_mi`
   - XS carries one patch on top (fix 4 memory leaks in error paths)

#### Recommendation

Keep `CONFIG_SCSI_LPFC=m` in-tree as the default; it supports all Emulex FC
HBAs, including the older generations the out-of-tree driver dropped. Ship
the out-of-tree module as an optional (non-default) driver only if we need
LPe38104S (G7S) or FC-SP authentication, which in-tree can't provide.
Making it the default would remove support for the pre-G6 HBAs.

### intel-i40e

Version: 2.28.16-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_I40E=m
CONFIG_I40E_DCB=y
CONFIG_IAVF=m
```
Version in-tree: none (`DRV_VERSION` was dropped upstream).

Main differences other than bug-fixes between the two upstream in-tree versions:
  - devlink support (info, port)
  - Energy Efficient Ethernet for X710 Base-T/KR/KX

Main differences between in-tree v6.12.115 and out-of-tree:
   - same PCI IDs
   - VF configuration through sysfs ("VF-d", `kcompat_vfd.c`): per-VF
     trust, MAC anti-spoof, VLAN strip, allow untagged/broadcast,
     loopback, ingress/egress/VLAN mirroring, stats
   - extra private flags: `mac-source-pruning`, `vf-source-pruning`,
     `mdd-auto-reset-vf`, `multiple-traffic-classes`
   - extra module parameter: `l4mode` (L4 cloud filter mode)
   - no devlink support in out-of-tree
   - XS carries two patches on top: a build fix and a PTP work queue
     corruption fix. The in-tree driver (6.12 and still 7.2) has the same
     bug (`INIT_WORK()` in `i40e_ptp_set_timestamp_mode()`)

#### Recommendation

Keep `CONFIG_I40E=m` in-tree as the default; it supports the same
hardware. Ship the out-of-tree module as an optional (non-default) driver
only if we need the VF-d sysfs interface or the extra VF private flags,
which in-tree can't provide. Port the XS PTP work queue fix to our
in-tree driver.

### intel-ice

Version: 2.6.4-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_ICE=m
CONFIG_ICE_HWMON=y
CONFIG_ICE_SWITCHDEV=y
CONFIG_ICE_HWTS=y
# CONFIG_INFINIBAND_IRDMA is not set
```
Version in-tree: none (`DRV_VERSION` was dropped upstream).

Main differences other than bug-fixes between the two upstream in-tree versions:
  - devlink subfunctions (SF netdev and representors)
  - packet parser, per-VF FDIR filter limit, DPLL embedded sync

Main differences between in-tree v6.12.115 and out-of-tree:
   - E835 family (0x1248-0x124A, 0x1261-0x1267) support which in-tree
     doesn't have (upstream in 6.17)
   - E830-CC SFP-DD (0x12D4) not supported by out-of-tree but is in-tree
     (other E830 IDs are the same, just renamed)
   - out-of-tree only: ACL filters, DCF, VF ADQ, VF live migration
     (`ice_migration.c`, `ice_vfio_pci.c`), per-VF sysfs entries
     (`rss_lut_vf_attr`, `transmit_lldp`)
   - extra private flags: FEC (`rs-fec`, `base-r-fec`,
     `allow-no-fec-modules-in-auto`), `mac-source-pruning`,
     `vf-source-pruning`, `block-dpll-freerun`, `channel-*` ADQ tuning
   - in-tree only: devlink subfunctions, eswitch bridge offload
   - XS ships the DDP package `ice-1.3.59.0.pkg` in `/lib/firmware/updates`.
     The in-tree driver also needs a DDP package (`intel/ice/ddp/ice.pkg`
     from linux-firmware), otherwise it runs in Safe Mode
   - XS carries one patch on top: "Fix enabling SR-IOV with Xen". It moves
     `pci_enable_sriov()` after the VF MSI-X setup so that Xen sees the
     right number of MSI-X entries, otherwise VF passthrough fails. The
     in-tree driver (6.12 and still 7.2) calls `pci_enable_sriov()` even
     earlier, so it most likely has the same problem

#### Recommendation

Keep `CONFIG_ICE=m` in-tree as the default; it supports the same
hardware except E835. Port the XS SR-IOV/Xen fix to our in-tree driver
(required for VF passthrough), and make sure we ship the ice DDP package.
Ship the out-of-tree module as an optional (non-default) driver only if we
need E835 support or the out-of-tree-only VF features (ADQ, live
migration).

### intel-igb

Version: 5.17.5-12
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_IGB=m
CONFIG_IGB_HWMON=y
CONFIG_IGB_DCA=y
CONFIG_IGBVF=m
```
Version in-tree: none (`DRV_VERSION` was dropped upstream).

Main differences other than bug-fixes between the two upstream in-tree versions:
  - nothing notable (MII write support, cleanups)

Main differences between in-tree v6.12.115 and out-of-tree:
   - same PCI IDs
   - out-of-tree only: VMDq, LRO, low latency interrupts, procfs
   - extra module parameters: `InterruptThrottleRate`, `IntMode`, `RSS`,
     `VMDQ`, `QueuePairs`, `LRO`, `EEE`, `DMAC`, `MDD`, `Node`,
     `LLIPort`/`LLIPush`/`LLISize`, `DisableHwReset`, `DumpBuffers`
     (in-tree only has `max_vfs` and `debug`)
   - in-tree only: XDP (and AF_XDP zero-copy upstream in 6.14+)
   - XS carries two patches on top: a build fix and a WoL fix to enable
     Wake-on-LAN by magic packet by default on I350, which is already the
     in-tree behaviour

#### Recommendation

Keep `CONFIG_IGB=m` in-tree; it supports the same hardware and the
out-of-tree driver mostly brings legacy tuning module parameters. No need
to ship the out-of-tree module.

### intel-ixgbe

Version: 6.1.5-10
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_IXGBE=m
CONFIG_IXGBE_HWMON=y
CONFIG_IXGBE_DCA=y
CONFIG_IXGBE_DCB=y
CONFIG_IXGBE_IPSEC=y
CONFIG_IXGBEVF=m
```
Version in-tree: none (`DRV_VERSION` was dropped upstream).

Main differences other than bug-fixes between the two upstream in-tree versions:
  - 1000BASE-BX support

Main differences between in-tree v6.12.115 and out-of-tree:
   - E610 family (10G-T, 2.5G-T, backplane, SFP, SGMII) support which
     in-tree doesn't have (upstream in 6.14, with devlink and firmware
     update)
   - X550EM_A QSFP / QSFP_N support which in-tree doesn't have (still not
     upstream in 7.2)
   - 82599 LS not supported by out-of-tree but is in-tree
   - out-of-tree only: devlink, firmware update, VMDq/VEPA, LRO, procfs
   - in-tree only: IPsec offload (`CONFIG_IXGBE_IPSEC`, incl. for VFs)
   - extra module parameters: `InterruptThrottleRate`, `IntMode`, `RSS`,
     `VMDQ`, `VEPA`, `MQ`, `LRO`, `FdirPballoc`, `AtrSampleRate`, `FCoE`,
     `MDD`, `vxlan_rx`, `LLI*`, ... (in-tree only has `max_vfs`, `debug`
     and `allow_unsupported_sfp`)
   - XS carries 4 patches on top: a build fix, two memory leak fixes
     already upstream, and "Avoid allocating order 1 RX buffers" which
     avoids excessive swiotlb usage on hardware that adds a timestamp to
     the frame. The in-tree driver (6.12 and still 7.2) has the same check
     (`max_frame > ETH_FRAME_LEN + ETH_FCS_LEN`)

#### Recommendation

Keep `CONFIG_IXGBE=m` in-tree as the default; it supports the same
hardware except E610 and X550EM_A QSFP. Port the XS "avoid order 1 RX
buffers" fix to our in-tree driver (swiotlb matters for a Xen dom0). Ship
the out-of-tree module as an optional (non-default) driver only if we need
E610 or X550EM_A QSFP support, or backport the upstream E610 support
instead.

### qlogic-qla2xxx

Version: 10.02.15.00_k-9.1
Variant: generic
Present in v6.12.115: Yes
Enabled in our kernel config for v9:
```
CONFIG_SCSI_QLA_FC=m
CONFIG_TCM_QLA2XXX=m
```
Version in-tree:
 - 6.6: 10.02.09.100-k
 - 6.12: 10.02.09.300-k
 - (7.2: 10.02.10.100-k)

Main differences other than bug-fixes between the two upstream in-tree versions:
  - nothing notable (fixes only)

Main differences between in-tree v6.12.115 and out-of-tree:
   - no new PCI IDs in out-of-tree
   - ISP8001/8021/8031/8044 (8100/8200/8300 series CNAs) not supported by
     out-of-tree but is in-tree
   - out-of-tree only: SAN congestion management (`qla_scm.c`,
     `ql2x_scmr_*` parameters), virtual lanes (`ql2xvirtuallane`), EDC,
     FC-NVMe boot/autoconnect udev rules and scripts (not packaged by XS)
   - in-tree only: target mode (`qla_target.c`, `qlini_mode`,
     `tcm_qla2xxx`). Out-of-tree builds a stub `tcm_qla2xxx`, and the XS
     depmod override applies to it too, so target mode is lost when the
     out-of-tree driver is used
   - other module parameter differences: out-of-tree adds
     `ql2xcache_valid_time`, `ql2xcontrol_edc_rdf`, `ql2xdebug`,
     `ql2xrspq_follow_inptr*`; in-tree only has `ql2xfc2target`,
     `ql2xtgt_tape_enable`, `ql2xuctrlirq`,
     `ql2xextended_error_logging_ktrace`
   - XS carries one patch on top: drop `OBJECT_FILES_NON_STANDARD` from the
     Makefile so objtool runs and live patches can apply. Not an issue for
     the in-tree driver

#### Recommendation

Keep `CONFIG_SCSI_QLA_FC=m` in-tree as the default; it supports more
hardware (8xxx CNAs) and target mode. Ship the out-of-tree module as an
optional (non-default) driver only if we need SAN congestion management
or virtual lanes, which in-tree can't provide.
