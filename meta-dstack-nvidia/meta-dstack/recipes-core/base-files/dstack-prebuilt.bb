SUMMARY = "Dstack base files"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/COPYING.MIT;md5=3da9cfbcb788c80a0384361b4de20420"

SRC_URI = "file://motd \
    file://dockerd_env"

inherit allarch

S = "${WORKDIR}"

do_install() {
    install -d ${D}${sysconfdir}/sysconfig/
    install -m 0644 ${S}/motd ${D}${sysconfdir}/motd
    install -m 0755 ${S}/dockerd_env ${D}${sysconfdir}/sysconfig/dockerd
}
