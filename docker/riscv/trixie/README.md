# xen-riscv64-trixie

Docker-based build and run environment for the Xen hypervisor on RISC-V 64-bit.
Targets QEMU `virt` with APLIC/IMSIC interrupt controllers.

The environment is a Linux/amd64 Debian Trixie cross-compiling for `riscv64`.
Pre-compiled binaries (kernel, QEMU, OpenSBI) are bundled in the image so you can
boot Xen without a local Linux build.

## Prerequisites

- Docker
- QEMU user-space emulators registered with `binfmt_misc` (see [First-time setup](#first-time-setup))
- Xen source tree from the [`dev-riscv-support-guest-domains`](https://gitlab.com/xen-project/people/olkur/xen/-/tree/dev-riscv-support-guest-domains?ref_type=heads) branch.

> **Note:** domU support is a work in progress. Currently only booting dom0 and running `xl info` / `xl list` are operational.

> [!WARNING]
> The Xen source tree must be on a branch with RISC-V support and have a **clean working tree**.
> Stale build artifacts or configuration files from a different branch can cause build failures.
> If you suspect a dirty state, you can run `make clean` to remove generated configuration files,
> so the next build will reconfigure from scratch. **Not recommended unless necessary**.

## First-time setup

Copy the local config template and fill in your paths:

```sh
cp config.mk.example config.mk
$EDITOR config.mk
```

> **Note:** `config.mk` is gitignored: each developer maintains their own copy.

Some RISC-V packages are installed via `dpkg` multi-arch and require QEMU user-space
emulation at build time. Register the emulators with:

```sh
make setup
```

> [!WARNING]
> `make setup` runs a `--privileged` container and modifies the host-wide
> `binfmt_misc` kernel subsystem. The registration is temporary and lost on reboot.
> Only run this on machines where you trust the effect of global binfmt changes.

## Configuration

Edit `config.mk` to configure your local environment.

| Variable   | Required | Default                                                                                          | Description                                            |
|------------|----------|--------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| `XEN_HOST` | Yes      | —                                                                                                | Path to the Xen source tree on your host               |
| `IMAGE`    | No       | [`baptleduc/xen-riscv64-trixie:latest`](https://hub.docker.com/r/baptleduc/xen-riscv64-trixie)  | Docker image to use (override for a local build)       |
| `KERNEL`   | No       | [`baptleduc/xen-riscv64-kernel`](https://hub.docker.com/r/baptleduc/xen-riscv64-kernel)         | Path to a local `Image.gz`, overrides the image default|
| `VMLINUX`  | No       | —                                                                                                | Path to `vmlinux`, enables Linux kernel symbols in GDB |

### Pre-built kernel

The default `Image.gz` is pulled from [`baptleduc/xen-riscv64-kernel`](https://hub.docker.com/r/baptleduc/xen-riscv64-kernel).
It is built from [`baptleduc/linux-xen-riscv`](https://github.com/baptleduc/linux-xen-riscv/tree/6.18-xen-guest-support),
a patched Linux tree adding RISC-V Xen guest support.
Versioned tags follow the `vX.X.X-xen-riscv` scheme.

To use a locally built kernel instead, set `KERNEL` in `config.mk`.

## Usage

```sh
make <target> [INITRD=initrd|initrd-tools]
```

### Targets

| Target          | Description                                          |
|-----------------|------------------------------------------------------|
| `setup`         | Register QEMU binfmt emulators (once after reboot)   |
| `build-image`   | Build the Docker image locally from `image/`         |
| `shell`         | Open an interactive shell in the container           |
| `run`           | Boot Xen + dom0 in QEMU                              |
| `run-rebuild`   | Rebuild Xen hypervisor, then boot                    |
| `debug`         | Boot Xen in QEMU, wait for GDB on port 1234          |
| `debug-rebuild` | Rebuild Xen, then boot in GDB-wait mode              |
| `gdb`           | Attach GDB (TUI) to a running Xen instance           |
| `gdb-rebuild`   | Rebuild Xen, then attach GDB                         |
| `clean`         | Remove generated config files, force reconfigure on next build |

### `INITRD` option

| Value          | Description                           |
|----------------|---------------------------------------|
| `initrd`       | Minimal initrd — default              |
| `initrd-tools` | Initrd with Xen tools included        |

```sh
make run INITRD=initrd-tools
```

## Common workflows

### Boot Xen with the bundled kernel

```sh
make run
```

### Boot Xen with a locally built kernel

Build the kernel from [`baptleduc/linux-xen-riscv`](https://github.com/baptleduc/linux-xen-riscv/tree/6.18-xen-guest-support):

```sh
make ARCH=riscv CROSS_COMPILE=riscv64-linux-gnu- -j$(nproc) xen_defconfig Image.gz
```

Then set `KERNEL` in `config.mk` and run:

```sh
# In config.mk:
# KERNEL := $(HOME)/path/to/linux/arch/riscv/boot/Image.gz
make run
```

### Rebuild Xen and boot

```sh
# With minimal initrd
make run-rebuild

# Also rebuild Xen tools and include them in the initrd
make run-rebuild INITRD=initrd-tools
```

### Debug with GDB (Xen symbols only)

In one terminal, start Xen waiting for GDB:
```sh
make debug
```

In another terminal, attach GDB:
```sh
make gdb
```

### Debug with GDB + Linux kernel symbols

Set `VMLINUX` in `config.mk`:
```makefile
VMLINUX := $(HOME)/path/to/linux/vmlinux
```

Then:
```sh
make debug   # terminal 1
make gdb     # terminal 2
```

### Build and use a local Docker image

```sh
make build-image IMAGE=xen-riscv64-trixie:dev
# In config.mk: IMAGE := xen-riscv64-trixie:dev
make run
```

## Directory structure

```
trixie/
  Makefile            Host-side Docker wrapper (this is what you invoke)
  config.mk.example   Local config template — copy to config.mk
  config.mk           Your local config (gitignored)
  image/              Docker image build context
    Dockerfile
    Makefile          In-container build/run targets
    generate_dtb.sh   QEMU device tree generation
    domu.cfg          DomU xl config
    xl.conf           xl global config
    config_*.status   Xen build configuration
```
