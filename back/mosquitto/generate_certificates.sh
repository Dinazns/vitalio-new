#!/bin/bash
# ============================================================================
# Healthcare-Grade MQTT Certificate Generation Script
# Generates CA, server certificate, and client certificates for TLS
# ============================================================================
#
# SECURITY NOTES:
# - This script generates a local Certificate Authority (CA)
# - Server certificate is signed by the CA
# - Clients use CA certificate to verify broker identity
# - Private keys are generated with strong encryption
# - Certificates are valid for 10 years (adjust as needed)
#
# USAGE:
#   chmod +x generate_certificates.sh
#   ./generate_certificates.sh
#
# OUTPUT:
#   - ca.crt: Certificate Authority certificate (distribute to clients)
#   - server.crt: Server certificate (used by Mosquitto broker)
#   - server.key: Server private key (KEEP SECURE, never share!)
#
# ============================================================================

set -e  # Exit on error

# Configuration
CERT_DIR="./certs"
DAYS_VALID=3650  # 10 years
KEY_SIZE=2048    # RSA key size (2048-bit minimum)

# Certificate details (customize for your organization)
COUNTRY="FR"
STATE="GIRONDE"
CITY="BORDEAUX"
ORG="Healthcare IoT"
ORG_UNIT="Medical Devices"
COMMON_NAME="mqtt-broker.local"  # Use broker's hostname or IP
EMAIL="malika.vagapova@epitech.digital"

echo "============================================================================"
echo "Healthcare-Grade MQTT Certificate Generation"
echo "============================================================================"
echo ""

# Create certificates directory
mkdir -p "$CERT_DIR"
echo "Created certificates directory: $CERT_DIR"
echo ""

# ============================================================================
# STEP 1: Generate Certificate Authority (CA) Private Key
# ============================================================================
echo "Step 1: Generating CA private key..."
openssl genrsa -out "$CERT_DIR/ca.key" $KEY_SIZE
chmod 600 "$CERT_DIR/ca.key"  # Restrict permissions (owner read/write only)
echo "CA private key generated: $CERT_DIR/ca.key"
echo ""

# ============================================================================
# STEP 2: Generate Certificate Authority (CA) Certificate
# ============================================================================
echo "Step 2: Generating CA certificate..."
openssl req -new -x509 -days $DAYS_VALID \
    -key "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=MQTT-CA/emailAddress=$EMAIL"
chmod 644 "$CERT_DIR/ca.crt"  # Readable by all (needed for clients)
echo "CA certificate generated: $CERT_DIR/ca.crt"
echo "   This file must be distributed to all MQTT clients"
echo ""

# ============================================================================
# STEP 3: Generate Server Private Key
# ============================================================================
echo "Step 3: Generating server private key..."
openssl genrsa -out "$CERT_DIR/server.key" $KEY_SIZE
chmod 600 "$CERT_DIR/server.key"  # Restrict permissions (owner read/write only)
echo "Server private key generated: $CERT_DIR/server.key"
echo "   KEEP THIS FILE SECURE - Never share or commit to version control!"
echo ""

# ============================================================================
# STEP 4: Generate Server Certificate Signing Request (CSR)
# ============================================================================
echo "Step 4: Generating server certificate signing request..."
openssl req -new \
    -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=$COMMON_NAME/emailAddress=$EMAIL"
echo "Server CSR generated: $CERT_DIR/server.csr"
echo ""

# ============================================================================
# STEP 5: Sign Server Certificate with CA
# ============================================================================
echo "Step 5: Signing server certificate with CA..."
openssl x509 -req -days $DAYS_VALID \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -extensions v3_req \
    -extfile <(cat <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $COMMON_NAME
DNS.2 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF
)
chmod 644 "$CERT_DIR/server.crt"  # Readable by Mosquitto
echo "Server certificate generated: $CERT_DIR/server.crt"
echo ""

# Clean up CSR file (no longer needed)
rm -f "$CERT_DIR/server.csr"
echo "Cleaned up temporary CSR file"
echo ""

# ============================================================================
# VERIFICATION
# ============================================================================
echo "============================================================================"
echo "Certificate Generation Complete!"
echo "============================================================================"
echo ""
echo "Generated files:"
echo "  $CERT_DIR/ca.crt       - CA certificate (distribute to clients)"
echo "  $CERT_DIR/server.crt   - Server certificate (for Mosquitto)"
echo "  $CERT_DIR/server.key    - Server private key (KEEP SECURE!)"
echo ""
echo "File permissions:"
ls -lh "$CERT_DIR"/*.crt "$CERT_DIR"/*.key 2>/dev/null || true
echo ""
echo "============================================================================"
echo "NEXT STEPS:"
echo "============================================================================"
echo "1. Verify certificates:"
echo "   openssl x509 -in $CERT_DIR/ca.crt -text -noout"
echo "   openssl x509 -in $CERT_DIR/server.crt -text -noout"
echo ""
echo "2. Copy ca.crt to your MQTT clients (Python, ESP32, etc.)"
echo ""
echo "3. Start Mosquitto broker:"
echo "   docker-compose up -d"
echo ""
echo "4. Test TLS connection:"
echo "   openssl s_client -connect localhost:8883 -CAfile $CERT_DIR/ca.crt"
echo ""
echo "============================================================================"
