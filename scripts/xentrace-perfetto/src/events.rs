//! Event IDs and names from xen/include/public/trace.h, plus the payload
//! knowledge (from tools/xentrace/xenalyze.c) needed for the events that are
//! turned into slices.

use std::borrow::Cow;

pub const TRC_LOST_RECORDS: u32 = 0x0001_f001;
pub const TRC_TRACE_CPU_CHANGE: u32 = 0x0001_f003;

/// Runstate changes encode `old << 8 | new << 4` into the event ID itself.
pub const TRC_SCHED_RUNSTATE_CHANGE: u32 = 0x0002_1001;
pub const RUNSTATE_CHANGE_MASK: u32 = 0x0fff_f00f;

pub const TRC_HVM_VMENTRY: u32 = 0x0008_1001;
pub const TRC_HVM_VMX_EXIT: u32 = 0x0008_1002;
pub const TRC_HVM_SVM_EXIT: u32 = 0x0008_1003;
pub const TRC_64_FLAG: u32 = 0x100;
pub const TRC_HVM_NESTEDFLAG: u32 = 0x400;

pub const TRC_PV_HYPERCALL_V2: u32 = 0x0020_100d;

pub const TRC_PM_FREQ_CHANGE: u32 = 0x0080_1001;
pub const TRC_PM_IDLE_ENTRY: u32 = 0x0080_1002;
pub const TRC_PM_IDLE_EXIT: u32 = 0x0080_1003;

pub const RUNSTATE_RUNNING: u32 = 0;

pub const DOMID_IDLE: u32 = 0x7fff;

const TRC_CLS_MASK: u32 = 0x0fff_0000;
const TRC_HVM_CLS: u32 = 0x0008_0000;
const TRC_PV_CLS: u32 = 0x0020_0000;
const TRC_SHADOW_CLS: u32 = 0x0040_0000;
const TRC_SCHED_CLASS: u32 = 0x0002_2000;

pub fn runstate_name(state: u32) -> &'static str {
    ["running", "runnable", "blocked", "offline"][(state & 3) as usize]
}

/// Strip the format flags that don't change an event's meaning.
pub fn normalize(event: u32) -> u32 {
    match event & TRC_CLS_MASK {
        TRC_HVM_CLS => event & !(TRC_64_FLAG | TRC_HVM_NESTEDFLAG),
        TRC_PV_CLS => event & !TRC_64_FLAG,
        // Shadow events carry the guest paging levels in bits 8-11.
        TRC_SHADOW_CLS => event & !0xf00,
        _ => event,
    }
}

pub fn event_name(event: u32) -> Cow<'static, str> {
    if let Some(n) = static_name(event).or_else(|| static_name(normalize(event))) {
        return n.into();
    }
    if event & RUNSTATE_CHANGE_MASK == TRC_SCHED_RUNSTATE_CHANGE {
        return format!(
            "runstate {}->{}",
            runstate_name(event >> 8),
            runstate_name(event >> 4)
        )
        .into();
    }
    if event & 0x0fff_f000 == TRC_SCHED_CLASS {
        let sched = match (event >> 9) & 7 {
            0 => "credit",
            1 => "credit2",
            3 => "arinc653",
            4 => "rtds",
            5 => "null",
            _ => "sched?",
        };
        return format!("{sched} evt {}", event & 0x1ff).into();
    }
    format!("event {event:#010x}").into()
}

fn static_name(event: u32) -> Option<&'static str> {
    Some(match event {
        0x0001_f001 => "lost_records",
        0x0001_f002 => "trace_wrap_buffer",
        0x0001_f003 => "trace_cpu_change",

        0x0002_1002 => "continue_running",
        0x0002_8001 => "sched_dom_add",
        0x0002_8002 => "sched_dom_rem",
        0x0002_8003 => "sched_sleep",
        0x0002_8004 => "sched_wake",
        0x0002_8005 => "sched_yield",
        0x0002_8006 => "sched_block",
        0x0002_8007 => "sched_shutdown",
        0x0002_8008 => "sched_ctl",
        0x0002_8009 => "sched_adjdom",
        0x0002_800a => "sched_switch",
        0x0002_800b => "sched_s_timer_fn",
        0x0002_800c => "sched_t_timer_fn",
        0x0002_800d => "sched_dom_timer_fn",
        0x0002_800e => "sched_switch_infprev",
        0x0002_800f => "sched_switch_infnext",
        0x0002_8010 => "sched_shutdown_code",
        0x0002_8011 => "sched_switch_infcont",

        0x0004_1001 => "dom0_dom_add",
        0x0004_1002 => "dom0_dom_rem",

        0x0010_f001 => "mem_page_grant_map",
        0x0010_f002 => "mem_page_grant_unmap",
        0x0010_f003 => "mem_page_grant_transfer",
        0x0010_f004 => "mem_set_p2m_entry",
        0x0010_f005 => "mem_decrease_reservation",
        0x0010_f010 => "mem_pod_populate",
        0x0010_f011 => "mem_pod_zero_reclaim",
        0x0010_f012 => "mem_pod_superpage_splinter",

        0x0020_1001 => "pv_hypercall",
        0x0020_1003 => "pv_trap",
        0x0020_1004 => "pv_page_fault",
        0x0020_1005 => "pv_forced_invalid_op",
        0x0020_1006 => "pv_emulate_privop",
        0x0020_1007 => "pv_emulate_4gb",
        0x0020_1008 => "pv_math_state_restore",
        0x0020_1009 => "pv_paging_fixup",
        0x0020_100a => "pv_gdt_ldt_mapping_fault",
        0x0020_100b => "pv_ptwr_emulation",
        0x0020_100c => "pv_ptwr_emulation_pae",
        0x0020_100d => "pv_hypercall_v2",
        0x0020_200e => "pv_hypercall_subcall",

        0x0040_f001 => "shadow_not_shadow",
        0x0040_f002 => "shadow_fast_propagate",
        0x0040_f003 => "shadow_fast_mmio",
        0x0040_f004 => "shadow_false_fast_path",
        0x0040_f005 => "shadow_mmio",
        0x0040_f006 => "shadow_fixup",
        0x0040_f007 => "shadow_domf_dying",
        0x0040_f008 => "shadow_emulate",
        0x0040_f009 => "shadow_emulate_unshadow_user",
        0x0040_f00a => "shadow_emulate_unshadow_evtinj",
        0x0040_f00b => "shadow_emulate_unshadow_unhandled",
        0x0040_f00c => "shadow_wrmap_bf",
        0x0040_f00d => "shadow_prealloc_unpin",
        0x0040_f00e => "shadow_resync_full",
        0x0040_f00f => "shadow_resync_only",

        0x0008_1001 => "vmentry",
        0x0008_1002 => "vmx_exit",
        0x0008_1003 => "svm_exit",
        0x0008_2001 => "pf_xen",
        0x0008_2002 => "pf_inject",
        0x0008_2003 => "inj_exc",
        0x0008_2004 => "inj_virq",
        0x0008_2005 => "reinj_virq",
        0x0008_2006 => "io_read",
        0x0008_2007 => "io_write",
        0x0008_2008 => "cr_read",
        0x0008_2009 => "cr_write",
        0x0008_200a => "dr_read",
        0x0008_200b => "dr_write",
        0x0008_200c => "msr_read",
        0x0008_200d => "msr_write",
        0x0008_200e => "cpuid",
        0x0008_200f => "intr",
        0x0008_2010 => "nmi",
        0x0008_2011 => "smi",
        0x0008_2012 => "vmmcall",
        0x0008_2013 => "hlt",
        0x0008_2014 => "invlpg",
        0x0008_2015 => "mce",
        0x0008_2016 => "ioport_read",
        0x0008_2017 => "iomem_read",
        0x0008_2018 => "clts",
        0x0008_2019 => "lmsw",
        0x0008_201a => "rdtsc",
        0x0008_2020 => "intr_window",
        0x0008_2021 => "npf",
        0x0008_2022 => "realmode_emulate",
        0x0008_2023 => "trap",
        0x0008_2024 => "trap_debug",
        0x0008_2025 => "vlapic",
        0x0008_2026 => "xcr_read",
        0x0008_2027 => "xcr_write",
        0x0008_2216 => "ioport_write",
        0x0008_2217 => "iomem_write",

        0x0008_4001 => "emul_hpet_start_timer",
        0x0008_4002 => "emul_pit_start_timer",
        0x0008_4003 => "emul_rtc_start_timer",
        0x0008_4004 => "emul_lapic_start_timer",
        0x0008_4005 => "emul_hpet_stop_timer",
        0x0008_4006 => "emul_pit_stop_timer",
        0x0008_4007 => "emul_rtc_stop_timer",
        0x0008_4008 => "emul_lapic_stop_timer",
        0x0008_4009 => "emul_pit_timer_cb",
        0x0008_400a => "emul_lapic_timer_cb",
        0x0008_400b => "emul_pic_int_output",
        0x0008_400c => "emul_pic_kick",
        0x0008_400d => "emul_pic_intack",
        0x0008_400e => "emul_pic_posedge",
        0x0008_400f => "emul_pic_negedge",
        0x0008_4010 => "emul_pic_pend_irq_call",
        0x0008_4011 => "emul_lapic_pic_intr",

        0x0080_1001 => "pm_freq_change",
        0x0080_1002 => "pm_idle_entry",
        0x0080_1003 => "pm_idle_exit",

        0x0080_2001 => "irq_move_cleanup_delay",
        0x0080_2002 => "irq_move_cleanup",
        0x0080_2003 => "irq_bind_vector",
        0x0080_2004 => "irq_clear_vector",
        0x0080_2005 => "irq_move_finish",
        0x0080_2006 => "irq_assign_vector",
        0x0080_2007 => "irq_unmapped_vector",
        0x0080_2008 => "irq_handled",
        _ => return None,
    })
}

/// Basic VMX exit reason (Intel SDM Vol. 3 Appendix C).
pub fn vmx_exit_name(reason: u32) -> Option<&'static str> {
    const NAMES: [&str; 76] = [
        "EXCEPTION_NMI",
        "EXTERNAL_INTERRUPT",
        "TRIPLE_FAULT",
        "INIT",
        "SIPI",
        "IO_SMI",
        "OTHER_SMI",
        "PENDING_VIRT_INTR",
        "PENDING_VIRT_NMI",
        "TASK_SWITCH",
        "CPUID",
        "GETSEC",
        "HLT",
        "INVD",
        "INVLPG",
        "RDPMC",
        "RDTSC",
        "RSM",
        "VMCALL",
        "VMCLEAR",
        "VMLAUNCH",
        "VMPTRLD",
        "VMPTRST",
        "VMREAD",
        "VMRESUME",
        "VMWRITE",
        "VMXOFF",
        "VMXON",
        "CR_ACCESS",
        "DR_ACCESS",
        "IO_INSTRUCTION",
        "MSR_READ",
        "MSR_WRITE",
        "INVALID_GUEST_STATE",
        "MSR_LOADING",
        "",
        "MWAIT_INSTRUCTION",
        "MONITOR_TRAP_FLAG",
        "",
        "MONITOR_INSTRUCTION",
        "PAUSE_INSTRUCTION",
        "MCE_DURING_VMENTRY",
        "",
        "TPR_BELOW_THRESHOLD",
        "APIC_ACCESS",
        "EOI_INDUCED",
        "ACCESS_GDTR_OR_IDTR",
        "ACCESS_LDTR_OR_TR",
        "EPT_VIOLATION",
        "EPT_MISCONFIG",
        "INVEPT",
        "RDTSCP",
        "VMX_PREEMPTION_TIMER_EXPIRED",
        "INVVPID",
        "WBINVD",
        "XSETBV",
        "APIC_WRITE",
        "RDRAND",
        "INVPCID",
        "VMFUNC",
        "ENCLS",
        "RDSEED",
        "PML_FULL",
        "XSAVES",
        "XRSTORS",
        "",
        "",
        "UMWAIT",
        "TPAUSE",
        "",
        "",
        "",
        "",
        "",
        "BUS_LOCK",
        "NOTIFY",
    ];
    NAMES
        .get((reason & 0xffff) as usize)
        .copied()
        .filter(|n| !n.is_empty())
}

/// SVM #VMEXIT code (AMD APM Vol. 2 Appendix C).
pub fn svm_exit_name(code: u32) -> Option<Cow<'static, str>> {
    const NAMES: [&str; 0x90 - 0x60] = [
        "INTR",
        "NMI",
        "SMI",
        "INIT",
        "VINTR",
        "CR0_SEL_WRITE",
        "IDTR_READ",
        "GDTR_READ",
        "LDTR_READ",
        "TR_READ",
        "IDTR_WRITE",
        "GDTR_WRITE",
        "LDTR_WRITE",
        "TR_WRITE",
        "RDTSC",
        "RDPMC",
        "PUSHF",
        "POPF",
        "CPUID",
        "RSM",
        "IRET",
        "SWINT",
        "INVD",
        "PAUSE",
        "HLT",
        "INVLPG",
        "INVLPGA",
        "IOIO",
        "MSR",
        "TASK_SWITCH",
        "FERR_FREEZE",
        "SHUTDOWN",
        "VMRUN",
        "VMMCALL",
        "VMLOAD",
        "VMSAVE",
        "STGI",
        "CLGI",
        "SKINIT",
        "RDTSCP",
        "ICEBP",
        "WBINVD",
        "MONITOR",
        "MWAIT",
        "MWAIT_CONDITIONAL",
        "XSETBV",
        "RDPRU",
        "EFER_WRITE_TRAP",
    ];
    Some(match code {
        0x00..=0x0f => format!("CR{}_READ", code).into(),
        0x10..=0x1f => format!("CR{}_WRITE", code - 0x10).into(),
        0x20..=0x2f => format!("DR{}_READ", code - 0x20).into(),
        0x30..=0x3f => format!("DR{}_WRITE", code - 0x30).into(),
        0x40..=0x5f => format!("EXCEPTION_{}", code - 0x40).into(),
        0x60..=0x8f => NAMES[(code - 0x60) as usize].into(),
        0x90..=0x9f => format!("CR{}_WRITE_TRAP", code - 0x90).into(),
        0xa0 => "INVLPGB".into(),
        0xa1 => "INVLPGB_ILLEGAL".into(),
        0xa2 => "INVPCID".into(),
        0xa3 => "MCOMMIT".into(),
        0xa4 => "TLBSYNC".into(),
        0xa5 => "BUS_LOCK".into(),
        0x400 => "NPF".into(),
        0x401 => "AVIC_INCOMPLETE_IPI".into(),
        0x402 => "AVIC_NOACCEL".into(),
        0x403 => "VMGEXIT".into(),
        0xffff_ffff => "INVALID".into(),
        _ => return None,
    })
}

/// Hypercall names (xen/include/public/xen.h `__HYPERVISOR_*`).
pub fn hypercall_name(op: u32) -> Option<&'static str> {
    const NAMES: [&str; 43] = [
        "set_trap_table",
        "mmu_update",
        "set_gdt",
        "stack_switch",
        "set_callbacks",
        "fpu_taskswitch",
        "sched_op_compat",
        "platform_op",
        "set_debugreg",
        "get_debugreg",
        "update_descriptor",
        "",
        "memory_op",
        "multicall",
        "update_va_mapping",
        "set_timer_op",
        "event_channel_op_compat",
        "xen_version",
        "console_io",
        "physdev_op_compat",
        "grant_table_op",
        "vm_assist",
        "update_va_mapping_otherdomain",
        "iret",
        "vcpu_op",
        "set_segment_base",
        "mmuext_op",
        "xsm_op",
        "nmi_op",
        "sched_op",
        "callback_op",
        "xenoprof_op",
        "event_channel_op",
        "physdev_op",
        "hvm_op",
        "sysctl",
        "domctl",
        "kexec_op",
        "tmem_op",
        "argo_op",
        "xenpmu_op",
        "dm_op",
        "hypfs_op",
    ];
    NAMES.get(op as usize).copied().filter(|n| !n.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert_eq!(event_name(0x0002_1011), "runstate running->runnable");
        assert_eq!(event_name(0x0008_2108), "cr_read"); // CR_READ64
        assert_eq!(event_name(0x0008_2216), "ioport_write");
        assert_eq!(event_name(0x0002_2203), "credit2 evt 3");
        assert_eq!(vmx_exit_name(48), Some("EPT_VIOLATION"));
        assert_eq!(svm_exit_name(0x7b).as_deref(), Some("IOIO"));
        assert_eq!(svm_exit_name(0x8f).as_deref(), Some("EFER_WRITE_TRAP"));
        assert_eq!(hypercall_name(42), Some("hypfs_op"));
    }
}
