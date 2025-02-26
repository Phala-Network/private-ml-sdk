#!/bin/bash
SCRIPT_DIR=$(cd $(dirname $0); pwd)
ACTION=$1

META_DIR=$SCRIPT_DIR
DSTACK_DIR=$SCRIPT_DIR/dstack
CERTS_DIR=`pwd`/certs
IMAGES_DIR=`pwd`/images
RUN_DIR=`pwd`/run
RUST_BUILD_DIR=`pwd`/rust-target
CERBOT_WORKDIR=$RUN_DIR/certbot
KMS_UPGRADE_REGISTRY_DIR=$RUN_DIR/kms/upgrade_registry
KMS_CERT_LOG_DIR=$RUN_DIR/kms/cert_log/

CONFIG_FILE=./build-config.sh

check_config() {
    local template_file=$1
    local config_file=$2

    # extract all variables in template file
    local variables=$(grep -oE '^\s*[A-Z_]+=' $template_file | sort)

    # check if each variable is set in config file
    local var missing=0
    for var in $variables; do
        if ! grep -qE "^\s*$var" $config_file; then
            echo "Variable $var is not set in $config_file"
            missing=1
        fi
    done
    if [ $missing -ne 0 ]; then
        return 1
    fi
    return 0
}

require_config() {
    cat <<EOF > build-config.sh.tpl
# base domain of kms rpc and tproxy rpc
# 1022.kvin.wang resolves to 10.0.2.2 which is host ip at the
# cvm point of view
KMS_DOMAIN=kms.1022.kvin.wang
TPROXY_DOMAIN=tproxy.1022.kvin.wang

TEEPOD_RPC_LISTEN_PORT=9080
# CIDs allocated to VMs start from this number of type unsigned int32
TEEPOD_CID_POOL_START=10000
# CID pool size
TEEPOD_CID_POOL_SIZE=1000
# Whether port mapping from host to CVM is allowed
TEEPOD_PORT_MAPPING_ENABLED=false
# Host API configuration, type of uint32
TEEPOD_VSOCK_LISTEN_PORT=9080

KMS_RPC_LISTEN_PORT=9043
TPROXY_RPC_LISTEN_PORT=9010

TPROXY_WG_INTERFACE=tproxy-$USER
TPROXY_WG_LISTEN_PORT=9182
TPROXY_WG_IP=10.0.3.1/24
TPROXY_WG_RESERVED_NET=10.0.3.1/32
TPROXY_SERVE_PORT=9443

BIND_PUBLIC_IP=0.0.0.0

TPROXY_PUBLIC_DOMAIN=app.kvin.wang
TPROXY_CERT=/etc/rproxy/certs/cert.pem
TPROXY_KEY=/etc/rproxy/certs/key.pem

# for certbot
CF_API_TOKEN=
CF_ZONE_ID=
ACME_URL=https://acme-staging-v02.api.letsencrypt.org/directory
EOF
    if [ -f $CONFIG_FILE ]; then
        source $CONFIG_FILE
        # check if any variable in build-config.sh.tpl is not set in build-config.sh.
        # This might occur if the build-config.sh is generated from and old repo.
        check_config build-config.sh.tpl $CONFIG_FILE
        if [ $? -ne 0 ]; then
            exit 1
        fi
        rm -f build-config.sh.tpl

        if [ -z "$TPROXY_SERVE_PORT" ]; then
            TPROXY_SERVE_PORT=${TPROXY_LISTEN_PORT1}
        fi
        TAPPD_PORT=8090
    else
        mv build-config.sh.tpl $CONFIG_FILE
        echo "Config file $CONFIG_FILE created, please edit it to configure the build"
        exit 1
    fi
}

# Step 1: build binaries
build_host() {
    echo "Building binaries"
    (cd $DSTACK_DIR && cargo build --release --target-dir ${RUST_BUILD_DIR})
    cp ${RUST_BUILD_DIR}/release/{tproxy,kms,teepod,certbot,ct_monitor,supervisor} .
}

# Step 2: build guest images
build_guest() {
    echo "Building guest images"
    if [ -z "$BBPATH" ]; then
        source $SCRIPT_DIR/dev-setup $1
    fi
    make -C $META_DIR dist DIST_DIR=$IMAGES_DIR BB_BUILD_DIR=${BBPATH}
}

# Step 4: generate config files

build_cfg() {
    echo "Building config files"
    TPROXY_WG_KEY=$(wg genkey)
    TPROXY_WG_PUBKEY=$(echo $TPROXY_WG_KEY | wg pubkey)
    # kms
    cat <<EOF > kms.toml
log_level = "info"

[rpc]
address = "127.0.0.1"
port = $KMS_RPC_LISTEN_PORT

[rpc.tls]
key = "$CERTS_DIR/rpc.key"
certs = "$CERTS_DIR/rpc.crt"

[rpc.tls.mutual]
ca_certs = "$CERTS_DIR/tmp-ca.crt"
mandatory = false

[core]
cert_dir = "$CERTS_DIR"

[core.auth_api]
type = "dev"

[core.onboard]
quote_enabled = false
address = "127.0.0.1"
port = $KMS_RPC_LISTEN_PORT
auto_bootstrap_domain = "$KMS_DOMAIN"
EOF

    # tproxy
    cat <<EOF > tproxy.toml
log_level = "info"
address = "127.0.0.1"
port = $TPROXY_RPC_LISTEN_PORT

[tls]
key = "$CERTS_DIR/tproxy-rpc.key"
certs = "$CERTS_DIR/tproxy-rpc.cert"

[tls.mutual]
ca_certs = "$CERTS_DIR/tproxy-ca.cert"
mandatory = false

[core]
kms_url = "https://localhost:$KMS_RPC_LISTEN_PORT"
rpc_domain = "$TPROXY_DOMAIN"
run_as_tapp = false

[core.sync]
enabled = true
interval = "30s"
my_url = "https://localhost:$TPROXY_RPC_LISTEN_PORT"
bootnode = "https://localhost:$TPROXY_RPC_LISTEN_PORT"

[core.certbot]
workdir = "$CERBOT_WORKDIR"

[core.wg]
private_key = "$TPROXY_WG_KEY"
public_key = "$TPROXY_WG_PUBKEY"
listen_port = $TPROXY_WG_LISTEN_PORT
ip = "$TPROXY_WG_IP"
reserved_net = "$TPROXY_WG_RESERVED_NET"
client_ip_range = "$TPROXY_WG_IP"
config_path = "$RUN_DIR/wg.conf"
interface = "$TPROXY_WG_INTERFACE"
endpoint = "10.0.2.2:$TPROXY_WG_LISTEN_PORT"

[core.proxy]
cert_chain = "$TPROXY_CERT"
cert_key = "$TPROXY_KEY"
base_domain = "$TPROXY_PUBLIC_DOMAIN"
listen_addr = "$BIND_PUBLIC_IP"
listen_port = $TPROXY_SERVE_PORT
tappd_port = $TAPPD_PORT
EOF

    # teepod
    cat <<EOF > teepod.toml
log_level = "info"
address = "127.0.0.1"
port = $TEEPOD_RPC_LISTEN_PORT
image_path = "$IMAGES_DIR"
run_path = "$RUN_DIR/vm"
kms_url = "https://localhost:$KMS_RPC_LISTEN_PORT"

[cvm]
kms_url = "https://$KMS_DOMAIN:$KMS_RPC_LISTEN_PORT"
tproxy_url = "https://$TPROXY_DOMAIN:$TPROXY_RPC_LISTEN_PORT"
cid_start = $TEEPOD_CID_POOL_START
cid_pool_size = $TEEPOD_CID_POOL_SIZE
[cvm.port_mapping]
enabled = $TEEPOD_PORT_MAPPING_ENABLED
address = "127.0.0.1"
range = [
    { protocol = "tcp", from = 1, to = 20000 },
]

[gateway]
base_domain = "$TPROXY_PUBLIC_DOMAIN"
port = $TPROXY_SERVE_PORT
tappd_port = $TAPPD_PORT

[host_api]
port = $TEEPOD_VSOCK_LISTEN_PORT
EOF

    cat <<EOF > certbot.toml
# Path to the working directory
workdir = "$CERBOT_WORKDIR"
# ACME server URL
acme_url = "$ACME_URL"
# Cloudflare API token
cf_api_token = "$CF_API_TOKEN"
# Cloudflare zone ID
cf_zone_id = "$CF_ZONE_ID"
# Auto set CAA record
auto_set_caa = true
# Domain to issue certificates for
domain = "*.$TPROXY_PUBLIC_DOMAIN"
# Renew interval in seconds
renew_interval = 3600
# Number of days before expiration to trigger renewal
renew_days_before = 10
# Renew timeout in seconds
renew_timeout = 120
EOF

    cat <<EOF > kms-allow-upgrade.sh
#!/bin/bash
if [ \$# -ne 2 ]; then
    echo "Usage: \$0 <app_id> <upgraded_app_id>"
    exit 1
fi
mkdir -p "$KMS_UPGRADE_REGISTRY_DIR/\$1"
touch "$KMS_UPGRADE_REGISTRY_DIR/\$1/\$2"
EOF
    chmod +x kms-allow-upgrade.sh
    mkdir -p $RUN_DIR
    mkdir -p $CERBOT_WORKDIR/backup/preinstalled
}

build_wg() {
    echo "Setting up wireguard interface"
    # Step 6: setup wireguard interface
    # Check if the WireGuard interface exists
    if ! ip link show $TPROXY_WG_INTERFACE &> /dev/null; then
        sudo ip link add $TPROXY_WG_INTERFACE type wireguard
        sudo ip address add $TPROXY_WG_IP dev $TPROXY_WG_INTERFACE
        sudo ip link set $TPROXY_WG_INTERFACE up
        echo "created and configured WireGuard interface $TPROXY_WG_INTERFACE"
    else
        echo "WireGuard interface $TPROXY_WG_INTERFACE already exists"
    fi
    # sudo ip route add $TPROXY_WG_CLIENT_IP_RANGE dev $TPROXY_WG_INTERFACE
}


case $ACTION in
    host)
        build_host
        ;;
    guest)
        build_guest $2
        ;;
    cfg)
        require_config
        build_cfg
        ;;
    certs)
        require_config
        ;;
    wg)
        require_config
        build_wg
        ;;
    "")
        # If no action specified, build everything
        require_config
        build_host
        build_guest
        build_cfg
        build_wg
        ;;
    *)
        echo "Invalid action: $ACTION"
        echo "Valid actions are: host, guest, cfg, certs, wg"
        exit 1
        ;;
esac
