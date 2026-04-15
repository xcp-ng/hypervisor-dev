# SPDX-FileCopyrightText: 2026 Baptiste Le Duc <baptiste.le-duc@vates.tech>
# SPDX-License-Identifier: GPL-2.0

nproc ?= $(shell nproc)

LINUX_ROOT?=$(BUILD_DIR)/linux
OPENSBI_ROOT?=$(BUILD_DIR)/opensbi

QEMU?=$(ARTIFACTS_DIR)/qemu-system-riscv64
OPENSBI?=$(ARTIFACTS_DIR)/opensbi-riscv64-generic-fw_dynamic.bin
KERNEL?=$(ARTIFACTS_DIR)/Image.gz

INITRD?=$(BUILD_DIR)/initrd.img
DTB_SCRIPT?=$(DTB_DIR)/generate_dtb.sh

XEN_ROOT?=$(BUILD_DIR)/xen
XEN_BIN?=$(XEN_ROOT)/xen/xen
XEN_SYMBOL?=$(XEN_ROOT)/xen/xen-syms
XEN_CONFIG?=$(XEN_ROOT)/xen/.config
XEN_CONFIGURE_OUT := $(XEN_ROOT)/config/Paths.mk

GDB?=/usr/bin/gdb-multiarch

INITRD_STAMP := .stamp_initrd_with_tools
XEN_MAKE := $(MAKE) -C $(XEN_ROOT) -j$(nproc)

QEMU_BASE_FLAGS = \
	-M virt,aclint=off,aia=aplic-imsic,aia-guests=7 \
	-cpu rv64,smstateen=on \
	-bios $(OPENSBI) \
	-smp 2 \
	-nographic \
	-m 2g \
	-kernel $(XEN_BIN) \
	-device loader,file=$(KERNEL),addr=0x808ef000 \
	-device loader,file=$(INITRD),addr=0x90400000 \
	-dtb $(DTB_DIR)/dom0-qemu-virt.dtb

QEMU_DEBUG_FLAGS = -s -S

GDB_FLAGS?=
GDB_ARGS = \
	-ex "set confirm off" \
	-ex "set architecture riscv:rv64"
ifndef VMLINUX
GDB_ARGS += \
	-ex "file $(XEN_SYMBOL)" \
	-ex "directory $(XEN_ROOT)"
else
GDB_ARGS += \
	-ex "file $(VMLINUX)" \
	-ex "directory $(XEN_ROOT)" \
	-ex "directory $(LINUX_ROOT)" \
	-ex "add-symbol-file $(XEN_SYMBOL)"
endif
GDB_ARGS += \
	-ex "target remote localhost:1234" \
	-ex "b start_xen" \
	-ex "c"

.PHONY: all clean help initrd-tools dist-tools dist-xen dist build-tools build-xen build go go-debug gdb initrd create-common-dirs create-tools-dirs

help: ## Display this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  %-16s %s\n", $$1, $$2}'

# --- Internal targets ---

$(XEN_CONFIGURE_OUT): $(XEN_ROOT)/configure
	cd $(XEN_ROOT) && ./configure --host=riscv64-linux-gnu

$(XEN_CONFIG):
	cp $(CONFIGS_DIR)/.config $(XEN_CONFIG)

$(INITRD_STAMP):
	touch $(INITRD_STAMP)

create-common-dirs:
	mkdir -p $(INITRD_DIR)/dev
	mkdir -p $(INITRD_DIR)/dist
	mkdir -p $(INITRD_DIR)/proc
	mkdir -p $(INITRD_DIR)/sys
	mkdir -p $(INITRD_DIR)/etc/init.d
	mkdir -p $(INITRD_DIR)/etc/xen

create-tools-dirs: create-common-dirs
	mkdir -p $(INITRD_DIR)/var/run/xenstored
	mkdir -p $(INITRD_DIR)/var/run/xen
	mkdir -p $(INITRD_DIR)/var/lib/xen
	mkdir -p $(INITRD_DIR)/var/lock
	mkdir -p $(INITRD_DIR)/var/log/xen
	mkdir -p $(INITRD_DIR)/domu
	cp $(CONFIGS_DIR)/xl.conf $(INITRD_DIR)/etc/xen/
	cp $(CONFIGS_DIR)/domu.cfg $(INITRD_DIR)/domu/
	cp $(KERNEL) $(INITRD_DIR)/domu/
	cp $(DOMU_INITRD_IMG) $(INITRD_DIR)/domu/initrd.img

# --- Build targets ---

# Uses the Xen top-level dist-tools (no -j bypass): replicating it requires
# running install-tools-public-headers first, which adds complexity.
dist-tools: $(XEN_CONFIGURE_OUT) ## Build and install Xen tools to /dist
	$(XEN_MAKE) dist-tools

# Use sub-make to preserve parallel build (-j$(nproc) not propagated by top-level Xen build)
dist-xen: $(XEN_CONFIG) $(XEN_CONFIGURE_OUT) ## Build and install Xen hypervisor to /dist
	$(MAKE) -C $(XEN_ROOT)/xen install DESTDIR=$(XEN_ROOT)/dist/install -j$(nproc)

dist: dist-tools dist-xen ## Build and install both tools and Xen to /dist

# Uses the Xen top-level build-tools (no -j bypass): same rationale as dist-tools.
build-tools: $(XEN_CONFIGURE_OUT) ## Build Xen tools
	$(XEN_MAKE) build-tools

# Use sub-make to preserve parallel build (-j$(nproc) not propagated by top-level Xen build)
build-xen: $(XEN_CONFIG) $(XEN_CONFIGURE_OUT) ## Build Xen hypervisor
	$(MAKE) -C $(XEN_ROOT)/xen -j$(nproc)

build: build-tools build-xen ## Build both Xen tools and hypervisor

# --- Initrd targets ---

initrd: $(INITRD_STAMP) create-common-dirs ## Create basic initrd image
	echo "Building initrd image"
	printf '%s\n' \
	'#!/bin/sh' \
	'echo "Hello RISC-V World!"' \
	'mount -t proc proc /proc' \
	'mount -t xenfs xenfs /proc/xen' \
	'mount -t sysfs sysfs /sys' \
	'exec /bin/sh' \
	> $(RCS_FILE) && \
	chmod +x $(RCS_FILE)
	cp $(RCS_FILE) $(INITRD_DIR)/etc/init.d/
	genext2fs -b 6500 -N 1024 -U -d $(INITRD_DIR)/ $(INITRD)

initrd-tools: dist-tools create-tools-dirs ## Create initrd with Xen tools included
	echo "Building initrd with tools image"
	cp -r $(XEN_ROOT)/dist/* $(INITRD_DIR)/dist/
	mv $(INITRD_DIR)/dist/install/usr/local/lib/* $(INITRD_DIR)/lib/
	printf '%s\n' \
	'#!/bin/sh' \
	'echo "Hello RISC-V World!"' \
	'mount -t proc proc /proc' \
	'mount -t xenfs xenfs /proc/xen' \
	'mkdir -p /dev/pts/' \
	'mount -t devpts devpts /dev/pts' \
	'mount -t sysfs sysfs /sys' \
	'export LIBXL_DEBUG_DUMP_DTB="/var/log/xen/debug_dump_dt.dtb"' \
	'export PATH=$$PATH:/dist/install/usr/local/sbin' \
	'xenstored' \
	'xenconsoled' \
	'sleep 0.5' \
	'./lib/xen/bin/xen-init-dom0' \
	'exec /bin/sh' \
	> $(RCS_FILE) && \
	chmod +x $(RCS_FILE)
	cp $(RCS_FILE) $(INITRD_DIR)/etc/init.d/
	genext2fs -b 200000 -N 1444 -U -d $(INITRD_DIR)/ $(INITRD)

# --- Run targets ---

go: $(INITRD) $(KERNEL) $(QEMU) $(OPENSBI) $(XEN_BIN) $(DTB_SCRIPT) ## Launch Xen with dom0 in QEMU
	cd $(DTB_DIR) && \
	bash $(DTB_SCRIPT) dom0-domU-test $(DTB_DIR) $(OPENSBI) $(QEMU) $(XEN_BIN) $(KERNEL) $(INITRD)
	$(QEMU) $(QEMU_BASE_FLAGS)

go-debug: $(INITRD) $(KERNEL) $(QEMU) $(OPENSBI) $(XEN_BIN) $(DTB_SCRIPT) ## Launch Xen in QEMU with GDB server waiting on port 1234
	cd $(DTB_DIR) && \
	bash $(DTB_SCRIPT) dom0-domU-test $(DTB_DIR) $(OPENSBI) $(QEMU) $(XEN_BIN) $(KERNEL) $(INITRD)
	$(QEMU) $(QEMU_BASE_FLAGS) $(QEMU_DEBUG_FLAGS)

gdb: $(GDB) ## Attach GDB to a running Xen instance
	$(GDB) $(GDB_FLAGS) $(GDB_ARGS)

# --- Clean ---

clean: ## Clean build artifacts (distclean)
	@if [ -f "$(XEN_CONFIGURE_OUT)" ]; then \
		rm -f "$(XEN_CONFIGURE_OUT)"; \
		echo "WARNING: removed $(XEN_CONFIGURE_OUT)"; \
		echo "WARNING: next builds will use the Docker image defaults (.config and ./configure output)"; \
	fi
	$(XEN_MAKE) distclean
