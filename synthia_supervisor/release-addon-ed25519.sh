
#!/usr/bin/env bash
set -euo pipefail
VERSION="$1"
ASSET_NAME="addon.tgz"
SIGNING_KEY="./keys/publisher_ed25519_private.pem"

tar -czf ${ASSET_NAME} manifest.json app frontend 2>/dev/null || true
SHA256=$(sha256sum ${ASSET_NAME} | awk '{print $1}')

DIGEST_BIN=$(mktemp)
openssl dgst -sha256 -binary ${ASSET_NAME} > ${DIGEST_BIN}
SIG_B64=$(openssl pkeyutl -sign -inkey ${SIGNING_KEY} -rawin -in ${DIGEST_BIN} | base64 -w0)
rm -f ${DIGEST_BIN}

echo "Version: ${VERSION}"
echo "SHA256: ${SHA256}"
echo "Signature (ed25519, Option A): ${SIG_B64}"
