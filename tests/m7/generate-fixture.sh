#!/bin/sh
set -eu
umask 077
# Prevent Git for Windows from rewriting OpenSSL subjects such as /CN=...
# while retaining its conversion of /d/... file paths for openssl.exe.
export MSYS2_ARG_CONV_EXCL='/CN='

tests_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
root="$tests_root/.m7-cluster"
if [ "${WEBOBS_M7_RESET:-false}" = true ]; then
    [ "$root" = "$tests_root/.m7-cluster" ] || {
        echo "refusing unexpected fixture reset path" >&2; exit 2;
    }
    rm -rf -- "$root"
fi
secrets="$root/secrets"
camera_count="${WEBOBS_M7_CAMERA_COUNT:-8}"
case "$camera_count" in ''|*[!0-9]*) echo "WEBOBS_M7_CAMERA_COUNT must be 8, 16, or 32" >&2; exit 2;; esac
[ "$camera_count" = 8 ] || [ "$camera_count" = 16 ] || [ "$camera_count" = 32 ] || {
    echo "WEBOBS_M7_CAMERA_COUNT must be 8, 16, or 32" >&2; exit 2;
}

mkdir -p "$secrets" "$root/minio-certs/CAs" "$root/minio" "$root/controller" \
    "$root/recordings/controller"
for node in recorder-a recorder-b recorder-c; do
    mkdir -p "$root/$node" "$root/recordings/$node" "$root/volumes/$node/hot"
    [ -f "$root/$node.env" ] || printf '%s\n' '# populated by bootstrap-cluster.py' > "$root/$node.env"
done

if [ ! -s "$secrets/cluster-ca.key" ] || [ ! -s "$secrets/cluster-ca.crt" ]; then
    openssl req -x509 -newkey ed25519 -nodes -days 3650 -subj '/CN=WebOBS M7 Fixture CA' \
        -keyout "$secrets/cluster-ca.key" -out "$secrets/cluster-ca.crt" >/dev/null 2>&1
fi
cat > "$root/server.ext" <<'EOF'
subjectAltName=DNS:controller,DNS:minio,DNS:mosquitto,IP:127.0.0.1
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF
openssl req -new -newkey rsa:2048 -nodes -subj '/CN=controller' \
    -keyout "$secrets/cluster-server.key" -out "$root/server.csr" >/dev/null 2>&1
openssl x509 -req -days 365 -in "$root/server.csr" -CA "$secrets/cluster-ca.crt" \
    -CAkey "$secrets/cluster-ca.key" -CAcreateserial -extfile "$root/server.ext" \
    -out "$secrets/cluster-server.crt" >/dev/null 2>&1
cp "$secrets/cluster-server.crt" "$root/minio-certs/public.crt"
cp "$secrets/cluster-server.key" "$root/minio-certs/private.key"
cp "$secrets/cluster-ca.crt" "$root/minio-certs/CAs/cluster-ca.crt"

printf '%s' 'gate-admin' > "$secrets/admin-user"
openssl rand -base64 32 | tr -d '\r\n' > "$secrets/admin-password"
openssl rand -hex 32 | tr -d '\r\n' > "$secrets/cluster-internal-token"
printf '%s' 'webobs-fixture' > "$secrets/minio-user"
openssl rand -base64 32 | tr -d '\r\n' > "$secrets/minio-password"
printf '%s\n' \
    'listener 8883 0.0.0.0' \
    'cafile /mosquitto/certs/cluster-ca.crt' \
    'certfile /mosquitto/certs/server.crt' \
    'keyfile /mosquitto/certs/server.key' \
    'user root' \
    'allow_anonymous true' \
    'persistence false' > "$root/mosquitto.conf"

python_bin=python3
python3 --version >/dev/null 2>&1 || python_bin=python
python_root="$root"
case "$(uname -s)" in MINGW*|MSYS*) python_root="$(cygpath -w "$root")";; esac
ROOT="$python_root" CAMERA_COUNT="$camera_count" "$python_bin" - <<'PY'
import json, os, pathlib
root = pathlib.Path(os.environ['ROOT'])
count = int(os.environ['CAMERA_COUNT'])
nodes = ['recorder-a', 'recorder-b', 'recorder-c']
access_key = (root / 'secrets/minio-user').read_text(encoding='utf-8')
secret_key = (root / 'secrets/minio-password').read_text(encoding='utf-8')
(root / 'secrets/minio-s3.json').write_text(json.dumps({
    'accessKeyId': access_key, 'secretAccessKey': secret_key,
}, separators=(',', ':')) + '\n', encoding='utf-8')
(root / 'secrets/mqtt.json').write_text(json.dumps({
    'host': 'mosquitto', 'port': 8883, 'topicPrefix': 'webobs/v1',
    'homeAssistantDiscoveryPrefix': 'homeassistant',
}, separators=(',', ':')) + '\n', encoding='utf-8')
for index, node in enumerate(nodes):
    cameras = []
    for camera in range(index + 1, count + 1, len(nodes)):
        cameras.append({
            'id': f'fixture-{camera:02d}', 'name': f'Synthetic {camera:02d}',
            'policy': 'continuous', 'mainUrl': 'rtsp://mediamtx:8554/synth',
            'stream': 'main', 'mode': 'copy', 'transport': 'tcp',
            'segmentSeconds': 10,
        })
    value = {'schemaVersion': 1, 'segmentSeconds': 10, 'maxAgeHours': 24,
             'maxBytes': 0, 'minFreeBytes': 0, 'cameras': cameras}
    (root / node / 'nvr.json').write_text(json.dumps(value, separators=(',', ':')) + '\n', encoding='utf-8')
    (root / node / 'archive.json').write_text(json.dumps({
        'endpoint': 'https://minio:9000', 'bucket': 'webobs-archive',
        'region': 'us-east-1', 'credentialsFile': '/run/secrets/minio-s3.json',
    }, separators=(',', ':')) + '\n', encoding='utf-8')
PY

chmod 0600 "$secrets"/* "$root"/minio-certs/* 2>/dev/null || true
echo "Generated isolated M7 fixture for $camera_count synthetic cameras."
