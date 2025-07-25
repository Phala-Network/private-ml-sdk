require libnvidia-container.inc

SUMMARY = "libNVIDIA Container for Yocto"

PACKAGECONFIG ??= "seccomp"
PACKAGECONFIG[seccomp] = "WITH_SECCOMP=yes,WITH_SECCOMP=no,libseccomp"

# We need to link with libelf, otherwise we need to
# include bmake-native which does not exist at the moment.
EXTRA_OEMAKE = "EXCLUDE_BUILD_FLAGS=1 PLATFORM=${HOST_ARCH} WITH_NVCGO=no WITH_LIBELF=yes WITH_SECCOMP=yes COMPILER=${@d.getVar('CC').split()[0]} REVISION=${SRCREV_libnvidia} ${PACKAGECONFIG_CONFARGS} \
                NVIDIA_MODPROBE_EXTRA_CFLAGS=${NVIDIA_MODPROBE_EXTRA_CFLAGS}"
NVIDIA_MODPROBE_EXTRA_CFLAGS ?= "-ffile-prefix-map=${WORKDIR}=/usr/src/debug/${PN}/${EXTENDPE}${PV}-${PR}"
CFLAGS:prepend = " -I${RECIPE_SYSROOT_NATIVE}/usr/include/tirpc "

export OBJCPY="${OBJCOPY}"
GO_IMPORT = "github.com/NVIDIA/nvidia-container-toolkit"
SECURITY_LDFLAGS = ""
LDFLAGS += "-Wl,-z,lazy"
GO_LINKSHARED = ""
REQUIRED_DISTRO_FEATURES = "virtualization"
do_configure:append() {
    # Mark Nvidia modprobe as downloaded
    touch ${S}/deps/src/nvidia-modprobe-${NVIDIA_MODPROBE_VERSION}/.download_stamp
}

do_compile:prepend() {
    # Ensure the copied bmake is used during the build
    export PATH=${WORKDIR}:$PATH
    
    #go fix
    export GOPATH="${WORKDIR}/go"
    export GOCACHE="${WORKDIR}/go-cache"
    mkdir -p ${GOPATH} ${GOCACHE}
}

do_compile:prepend() {
    export CURL="curl --insecure"
}

do_compile() {
    oe_runmake
}

do_install() {
    oe_runmake install DESTDIR=${D}
    install -d ${D}${sysconfdir}/nvidia-container-runtime
    # install -m 0644 ${S}/src/${GO_IMPORT}/config/config.toml.ubuntu ${D}${sysconfdir}/nvidia-container-runtime/config.toml
    # sed -i -e's,ldconfig\.real,ldconfig,' ${D}${sysconfdir}/nvidia-container-runtime/config.toml
    # sed -i -e's,mode = "auto",mode = "legacy",' ${D}${sysconfdir}/nvidia-container-runtime/config.toml
    ln -sf nvidia-container-runtime-hook ${D}${bindir}/nvidia-container-toolkit
}

FILES_${PN} += "/usr/local/bin /usr/local/lib"

RDEPENDS:${PN}:append = " ldconfig"

do_compile[network] = "1"

# Added to skip buildpath QA errors for files generated by rpcgen
INSANE_SKIP:${PN}-src = "buildpaths"
