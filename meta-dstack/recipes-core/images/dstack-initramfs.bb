PACKAGE_INSTALL = "${VIRTUAL-RUNTIME_base-utils} udev base-passwd ${ROOTFS_BOOTSTRAP_INSTALL} base-files"
PACKAGE_INSTALL += "kernel-module-tdx-guest"
PACKAGE_INSTALL += "dstack-guest curl jq"

# Do not pollute the initrd image with rootfs features
IMAGE_FEATURES = ""

# Don't allow the initramfs to contain a kernel
PACKAGE_EXCLUDE = "kernel-image-*"

IMAGE_NAME_SUFFIX ?= ""
IMAGE_LINGUAS = ""
IMAGE_NAME = "dstack-initramfs"

LICENSE = "MIT"

IMAGE_FSTYPES = "${INITRAMFS_FSTYPES}"
inherit core-image

IMAGE_ROOTFS_SIZE = "8192"
IMAGE_ROOTFS_EXTRA_SPACE = "0"

# Use the same restriction as initramfs-module-install
COMPATIBLE_HOST = '(x86_64.*|i.86.*|arm.*|aarch64.*|loongarch64.*)-(linux.*|freebsd.*)'

# Remove sysvinit related files in a postprocess function
ROOTFS_POSTPROCESS_COMMAND += "postprocess_initramfs;"

postprocess_initramfs() {
    install -m 0755 ${THISDIR}/files/init ${IMAGE_ROOTFS}/init

    rm -rf ${IMAGE_ROOTFS}${sysconfdir}/init.d
    rm -rf ${IMAGE_ROOTFS}${systemd_system_unitdir}
    rm -rf ${IMAGE_ROOTFS}${bindir}/tappd
}
