# ============================================================================
# Healthcare-Grade MQTT Certificate Generation Script (PowerShell)
# Generates CA, server certificate for TLS
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
#   .\generate_certificates.ps1
#
# PREREQUISITES:
#   - OpenSSL must be installed and in PATH
#   - Run PowerShell as Administrator (for certificate store access, optional)
#
# OUTPUT:
#   - ca.crt: Certificate Authority certificate (distribute to clients)
#   - server.crt: Server certificate (used by Mosquitto broker)
#   - server.key: Server private key (KEEP SECURE, never share!)
#
# ============================================================================

$ErrorActionPreference = "Stop"

# Configuration
$CERT_DIR = ".\certs"
$DAYS_VALID = 3650  # 10 years
$KEY_SIZE = 2048    # RSA key size (2048-bit minimum)

# Certificate details
$COUNTRY = "FR"
$STATE = "GIRONDE"
$CITY = "BORDEAUX"
$ORG = "Healthcare IoT"
$ORG_UNIT = "Medical Devices"
$COMMON_NAME = "mqtt-broker.local"  # Use your broker's hostname or IP
$EMAIL = "malika.vagapova@epitech.digital"

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Healthcare-Grade MQTT Certificate Generation" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Check if OpenSSL is available
$opensslPath = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $opensslPath) {
    Write-Host "ERROR: OpenSSL not found in PATH" -ForegroundColor Red
    Write-Host "   Please install OpenSSL and ensure it's in your system PATH" -ForegroundColor Yellow
    Write-Host "   Download from: https://slproweb.com/products/Win32OpenSSL.html" -ForegroundColor Yellow
    exit 1
}

# Create certificates directory
if (-not (Test-Path $CERT_DIR)) {
    New-Item -ItemType Directory -Path $CERT_DIR | Out-Null
}
Write-Host "Created certificates directory: $CERT_DIR" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 1: Generate Certificate Authority (CA) Private Key
# ============================================================================
Write-Host "Step 1: Generating CA private key..." -ForegroundColor Yellow
& openssl genrsa -out "$CERT_DIR\ca.key" $KEY_SIZE
if ($LASTEXITCODE -ne 0) { throw "Failed to generate CA key" }
icacls "$CERT_DIR\ca.key" /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
Write-Host "CA private key generated: $CERT_DIR\ca.key" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 2: Generate Certificate Authority (CA) Certificate
# ============================================================================
Write-Host "Step 2: Generating CA certificate..." -ForegroundColor Yellow
$subject = "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=MQTT-CA/emailAddress=$EMAIL"
& openssl req -new -x509 `
  -config "$env:OPENSSL_CONF" `
  -days $DAYS_VALID `
  -key "$CERT_DIR\ca.key" `
  -out "$CERT_DIR\ca.crt" `
  -subj $subject
if ($LASTEXITCODE -ne 0) { throw "Failed to generate CA certificate" }
Write-Host "CA certificate generated: $CERT_DIR\ca.crt" -ForegroundColor Green
Write-Host "   This file must be distributed to all MQTT clients" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# STEP 3: Generate Server Private Key
# ============================================================================
Write-Host "Step 3: Generating server private key..." -ForegroundColor Yellow
& openssl genrsa -out "$CERT_DIR\server.key" $KEY_SIZE
if ($LASTEXITCODE -ne 0) { throw "Failed to generate server key" }
icacls "$CERT_DIR\server.key" /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
Write-Host "Server private key generated: $CERT_DIR\server.key" -ForegroundColor Green
    Write-Host "   KEEP THIS FILE SECURE - Never share or commit to version control!" -ForegroundColor Red
Write-Host ""

# ============================================================================
# STEP 4: Generate Server Certificate Signing Request (CSR)
# ============================================================================
Write-Host "Step 4: Generating server certificate signing request..." -ForegroundColor Yellow
$serverSubject = "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=$COMMON_NAME/emailAddress=$EMAIL"
& openssl req -new `
  -config "$env:OPENSSL_CONF" `
  -key "$CERT_DIR\server.key" `
  -out "$CERT_DIR\server.csr" `
  -subj $serverSubject
if ($LASTEXITCODE -ne 0) { throw "Failed to generate server CSR" }
Write-Host "Server CSR generated: $CERT_DIR\server.csr" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 5: Create OpenSSL config file for server certificate extensions
# ============================================================================
Write-Host "Step 5: Creating OpenSSL config for server certificate..." -ForegroundColor Yellow
$opensslConfig = @"
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = $COUNTRY
ST = $STATE
L = $CITY
O = $ORG
OU = $ORG_UNIT
CN = $COMMON_NAME
emailAddress = $EMAIL

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $COMMON_NAME
DNS.2 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
"@
$opensslConfig | Out-File -FilePath "$CERT_DIR\server.conf" -Encoding ASCII

# ============================================================================
# STEP 6: Sign Server Certificate with CA
# ============================================================================
Write-Host "Step 6: Signing server certificate with CA..." -ForegroundColor Yellow
& openssl x509 -req -days $DAYS_VALID `
    -in "$CERT_DIR\server.csr" `
    -CA "$CERT_DIR\ca.crt" `
    -CAkey "$CERT_DIR\ca.key" `
    -CAcreateserial `
    -out "$CERT_DIR\server.crt" `
    -extensions v3_req `
    -extfile "$CERT_DIR\server.conf"
if ($LASTEXITCODE -ne 0) { throw "Failed to sign server certificate" }
Write-Host "Server certificate generated: $CERT_DIR\server.crt" -ForegroundColor Green
Write-Host ""

# Clean up temporary files
Remove-Item "$CERT_DIR\server.csr" -ErrorAction SilentlyContinue
Remove-Item "$CERT_DIR\server.conf" -ErrorAction SilentlyContinue
Write-Host "Cleaned up temporary files" -ForegroundColor Green
Write-Host ""

# ============================================================================
# VERIFICATION
# ============================================================================
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Certificate Generation Complete!" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Generated files:" -ForegroundColor Yellow
Write-Host "  $CERT_DIR\ca.crt       - CA certificate (distribute to clients)" -ForegroundColor White
Write-Host "  $CERT_DIR\server.crt   - Server certificate (for Mosquitto)" -ForegroundColor White
Write-Host "  $CERT_DIR\server.key    - Server private key (KEEP SECURE!)" -ForegroundColor White
Write-Host ""
Write-Host "File permissions:" -ForegroundColor Yellow
Get-ChildItem "$CERT_DIR\*.crt", "$CERT_DIR\*.key" | Format-Table Name, Length, LastWriteTime -AutoSize
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "NEXT STEPS:" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "1. Verify certificates:" -ForegroundColor Yellow
Write-Host "   openssl x509 -in $CERT_DIR\ca.crt -text -noout" -ForegroundColor White
Write-Host "   openssl x509 -in $CERT_DIR\server.crt -text -noout" -ForegroundColor White
Write-Host ""
Write-Host "2. Copy ca.crt to your MQTT clients (Python, ESP32, etc.)" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Start Mosquitto broker:" -ForegroundColor Yellow
Write-Host "   docker-compose up -d" -ForegroundColor White
Write-Host ""
Write-Host "4. Test TLS connection:" -ForegroundColor Yellow
Write-Host "   openssl s_client -connect localhost:8883 -CAfile $CERT_DIR\ca.crt" -ForegroundColor White
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
