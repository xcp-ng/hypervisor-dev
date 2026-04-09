# SPDX-FileCopyrightText: 2026 Baptiste Le Duc <baptiste.leduc@etik.com>
# SPDX-License-Identifier: GPL-2.0

# ==============================================================================
# Host-side Docker wrapper for Xen RISC-V / xen-riscv64-trixie
#
# Usage: make <target> [INITRD=initrd|initrd-tools] [IMAGE=<tag>]
#
# Before first use: copy config.mk.example to config.mk and set your paths.
# ==============================================================================

-include config.mk

ifndef XEN_HOST
$(error XEN_HOST is not set. Copy config.mk.example to config.mk and fill in your paths.)
endif

IMAGE ?= baptleduc/xen-riscv64-trixie:latest
$(info )
$(info Image: $(IMAGE))
$(info )

BUILD_DIR := /build
XEN_DIR   := $(BUILD_DIR)/xen

DOCKER := docker run --rm -it \
	--platform linux/amd64 \
	-v "$(XEN_HOST)":$(XEN_DIR)

# Override the pre-compiled kernel bundled in the Docker image
ifdef KERNEL
DOCKER += -v "$(KERNEL)":/build/kernel/Image.gz \
          -e "KERNEL=/build/kernel/Image.gz"
endif

# Mount vmlinux for GDB kernel symbol loading
ifdef VMLINUX
DOCKER += -v "$(VMLINUX)":/build/vmlinux \
          -e "VMLINUX=/build/vmlinux"
endif

INITRD ?= initrd
VALID_INITRD := initrd initrd-tools
ifneq ($(filter $(INITRD),$(VALID_INITRD)),$(INITRD))
$(error INITRD must be one of: $(VALID_INITRD) (got '$(INITRD)'))
endif

.PHONY: help setup build-image shell run run-rebuild debug debug-rebuild gdb gdb-rebuild

help: ## Show this help message
	@echo "Targets:"
	@grep -hE '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  %-16s %s\n", $$1, $$2}'
	@echo ""
	@echo "Options:"
	@echo "  INITRD=initrd        Minimal initrd (default)"
	@echo "  INITRD=initrd-tools  Initrd with Xen tools included"
	@echo "  IMAGE=<tag>          Docker image (default: $(IMAGE))"
	@echo "  KERNEL=<path>        Local kernel binary, overrides the image default"
	@echo "  VMLINUX=<path>       Path to vmlinux, enables kernel symbols in GDB"
	@echo ""
	@echo "Local config: config.mk (copy from config.mk.example)"

setup: ## Register QEMU binfmt emulators (run once after each reboot)
	docker run --rm --privileged multiarch/qemu-user-static --reset -p yes

build-image: ## Build the Docker image locally from image/
	docker build --platform linux/amd64 -f image/Dockerfile -t $(IMAGE) image/

shell: ## Open an interactive shell in the container
	$(DOCKER) -p 1234:1234 $(IMAGE) /bin/bash

run: ## Boot Xen + dom0 in QEMU
	$(DOCKER) -p 1234:1234 $(IMAGE) \
		/bin/bash -c "make $(INITRD) && make go"

run-rebuild: ## Rebuild Xen hypervisor, then boot
	$(DOCKER) -p 1234:1234 $(IMAGE) \
		/bin/bash -c "make -C $(XEN_DIR)/xen -j$$(nproc) && make $(INITRD) && make go"

debug: ## Boot Xen in QEMU, wait for GDB on port 1234
	$(DOCKER) -p 1234:1234 $(IMAGE) \
		/bin/bash -c "make $(INITRD) && make go-debug"

debug-rebuild: ## Rebuild Xen, then boot in GDB-wait mode
	$(DOCKER) -p 1234:1234 $(IMAGE) \
		/bin/bash -c "make -C $(XEN_DIR)/xen -j$$(nproc) && make $(INITRD) && make go-debug"

# VMLINUX is optional: without it, GDB loads Xen symbols only.
gdb: ## Attach GDB (TUI) to a running Xen instance
ifndef VMLINUX
	$(warning VMLINUX is not set: Linux kernel symbols will not be loaded. Set VMLINUX in config.mk to enable them.)
endif
	$(DOCKER) --network host $(IMAGE) \
		/bin/bash -c "make gdb GDB_FLAGS=-tui"

gdb-rebuild: ## Rebuild Xen, then attach GDB
ifndef VMLINUX
	$(warning VMLINUX is not set: Linux kernel symbols will not be loaded. Set VMLINUX in config.mk to enable them.)
endif
	$(DOCKER) --network host $(IMAGE) \
		/bin/bash -c "make -C $(XEN_DIR)/xen -j$$(nproc) && make gdb GDB_FLAGS=-tui"
