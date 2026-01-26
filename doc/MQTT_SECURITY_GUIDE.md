# Healthcare-Grade MQTT Security Implementation Guide

## Overview

This guide documents the complete security implementation for the Eclipse Mosquitto MQTT broker, configured to meet healthcare-grade security requirements for medical IoT devices.

**Security Level:** Production / Healthcare IoT  
**Compliance:** HIPAA-ready, auditable, production-grade

---

## Table of Contents

1. [Security Requirements](#security-requirements)
2. [Architecture Overview](#architecture-overview)
3. [Certificate Generation](#certificate-generation)
4. [Password File Setup](#password-file-setup)
5. [Docker Deployment](#docker-deployment)
6. [Client Configuration](#client-configuration)
7. [Testing & Verification](#testing--verification)
8. [Troubleshooting](#troubleshooting)
9. [Security Audit Checklist](#security-audit-checklist)

---

## Security Requirements

### Implemented Security Features

1. **Disabled Unencrypted MQTT (Port 1883)**
   - Port 1883 is completely disabled
   - No fallback to insecure connections
   - Only TLS-encrypted port 8883 is exposed

2. **Enabled MQTT over TLS (Port 8883)**
   - All MQTT traffic encrypted using TLS 1.2+
   - Certificate-based broker authentication
   - Client certificate validation

3. **X.509 Certificate Authentication**
   - Local Certificate Authority (CA) generated
   - Server certificate signed by CA
   - Clients verify broker identity using CA certificate

4. **TLS 1.2+ Encryption**
   - Minimum TLS version: 1.2 (enforced)
   - Strong cipher suites only
   - No weak protocols or ciphers

5. **Anonymous Access Disabled**
   - `allow_anonymous false` in configuration
   - All connections require username/password
   - No unauthenticated access possible

6. **Username/Password Authentication**
   - Bcrypt-hashed passwords (not plaintext)
   - Password file with restricted permissions
   - Per-user authentication

7. **Docker Compatibility**
   - Volume mounts for certificates and configuration
   - Only secure port exposed
   - Production-ready deployment

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    MQTT Broker (Mosquitto)                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Port 8883 (TLS-encrypted MQTT)                       │  │
│  │  - Server Certificate: server.crt                     │  │
│  │  - Server Private Key: server.key                     │  │
│  │  - CA Certificate: ca.crt                             │  │
│  │  - Password File: passwd (username/password auth)     │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ TLS 1.2+
                          │ Username/Password
                          │ CA Certificate Validation
        ┌─────────────────┴─────────────────┐
        │                                   │
┌───────┴────────┐                  ┌──────┴────────┐
│  IoT Devices   │                  │  Backend API   │
│  (ESP32/Sim)   │                  │  (Python)      │
│                │                  │                │
│  - ca.crt      │                  │  - ca.crt      │
│  - Username    │                  │  - Username    │
│  - Password    │                  │  - Password    │
└────────────────┘                  └────────────────┘
```

---

## Certificate Generation

### Prerequisites

- **OpenSSL** installed and in PATH
- **PowerShell** (Windows) or **Bash** (Linux/Mac)

### Step 1: Generate Certificates

#### Windows (PowerShell)

```powershell
cd mosquitto
.\generate_certificates.ps1
```

#### Linux/Mac (Bash)

```bash
cd mosquitto
chmod +x generate_certificates.sh
./generate_certificates.sh
```

### Step 2: Verify Certificate Generation

The script generates three critical files:

```
mosquitto/certs/
├── ca.crt       # Certificate Authority (distribute to all clients)
├── server.crt   # Server certificate (used by Mosquitto)
└── server.key   # Server private key (KEEP SECURE!)
```

**SECURITY WARNING:**
- `server.key` is the broker's private key
- **NEVER** share or commit this file to version control
- File permissions are automatically restricted (600)

### Step 3: Verify Certificates

```bash
# View CA certificate details
openssl x509 -in mosquitto/certs/ca.crt -text -noout

# View server certificate details
openssl x509 -in mosquitto/certs/server.crt -text -noout

# Verify server certificate is signed by CA
openssl verify -CAfile mosquitto/certs/ca.crt mosquitto/certs/server.crt
```

### Certificate Details

- **Validity:** 10 years (3650 days)
- **Key Size:** 2048-bit RSA (healthcare minimum)
- **TLS Version:** 1.2+ enforced
- **Subject Alternative Names:** localhost, 127.0.0.1, ::1

---

## Password File Setup

### Step 1: Create Password File

#### Windows (PowerShell)

```powershell
cd mosquitto
.\setup_password_file.ps1 -Create -Username <your_username>
```

#### Linux/Mac (Bash)

```bash
cd mosquitto
chmod +x setup_password_file.sh
./setup_password_file.sh -c -u <your_username>
```

### Step 2: Add Additional Users

```powershell
# Windows
.\setup_password_file.ps1 -Add -Username <another_username>

# Linux/Mac
./setup_password_file.sh -a -u <another_username>
```

### Step 3: List Users

```powershell
# Windows
.\setup_password_file.ps1 -List

# Linux/Mac
./setup_password_file.sh -l
```

### Step 4: Remove Users

```powershell
# Windows
.\setup_password_file.ps1 -Remove -Username <username>

# Linux/Mac
./setup_password_file.sh -r -u <username>
```

### Password File Security

- **Location:** `mosquitto/passwd`
- **Format:** `username:bcrypt_hash` (not plaintext)
- **Permissions:** 600 (owner read/write only)
- **Encryption:** Bcrypt (industry-standard hashing)

---

## Docker Deployment

### Step 1: Verify Certificates Exist

```powershell
# Verify all required files exist
Test-Path mosquitto/certs/ca.crt
Test-Path mosquitto/certs/server.crt
Test-Path mosquitto/certs/server.key
Test-Path mosquitto/passwd
```

### Step 2: Start Mosquitto Broker

```powershell
docker-compose up -d
```

### Step 3: Verify Container is Running

```powershell
docker ps
docker logs mosquitto
```

### Step 4: Verify Only Secure Port is Exposed

```powershell
# Should show port 8883 only (not 1883)
docker port mosquitto
```

### Docker Volume Mounts

```
mosquitto/
├── mosquitto.conf    → /mosquitto/config/mosquitto.conf
├── certs/
│   ├── ca.crt       → /mosquitto/certs/ca.crt
│   ├── server.crt   → /mosquitto/certs/server.crt
│   └── server.key   → /mosquitto/certs/server.key
├── passwd            → /mosquitto/passwd
├── data/             → /mosquitto/data (persistence)
└── log/              → /mosquitto/log (logs)
```

---

## Client Configuration

### Python Client (paho-mqtt)

#### Environment Variables

Create or update `.env` file:

```env
# MQTT Configuration (TLS)
MQTT_BROKER=localhost
MQTT_PORT=8883
MQTT_USERNAME=your_username
MQTT_PASSWORD=your_password
MQTT_CA_CERT=./mosquitto/certs/ca.crt
```

#### Example: Backend Subscriber (api.py)

The `api.py` file is already configured for TLS. Ensure environment variables are set:

```python
# TLS configuration is automatic
# Just set environment variables:
# - MQTT_BROKER
# - MQTT_PORT (default: 8883)
# - MQTT_USERNAME
# - MQTT_PASSWORD
# - MQTT_CA_CERT (default: ./mosquitto/certs/ca.crt)
```

#### Example: IoT Publisher (data.py)

The `data.py` file is already configured for TLS. Set environment variables:

```python
# Environment variables required:
# - MQTT_BROKER (default: localhost)
# - MQTT_PORT (default: 8883)
# - MQTT_USERNAME (required)
# - MQTT_PASSWORD (required)
# - MQTT_CA_CERT (default: ./mosquitto/certs/ca.crt)
# - DEVICE_ID (default: SIM-ESP32-001)
```

### ESP32 Client Configuration

For ESP32 devices, you'll need to:

1. **Embed CA Certificate:**
   ```cpp
   // In your ESP32 code
   const char* ca_cert = R"(
   -----BEGIN CERTIFICATE-----
   ... (contents of ca.crt)
   -----END CERTIFICATE-----
   )";
   ```

2. **Configure TLS:**
   ```cpp
   WiFiClientSecure client;
   client.setCACert(ca_cert);
   ```

3. **Set Username/Password:**
   ```cpp
   mqttClient.setCredentials("username", "password");
   ```

4. **Connect via Port 8883:**
   ```cpp
   mqttClient.begin("broker_address", 8883, client);
   ```

---

## Testing & Verification

### Test 1: Verify TLS Connection

```bash
# Test TLS handshake
openssl s_client -connect localhost:8883 -CAfile mosquitto/certs/ca.crt
```

**Expected Output:**
- `Verify return code: 0 (ok)`
- TLS version: TLSv1.2 or TLSv1.3
- Certificate chain verified

### Test 2: Verify Unencrypted Port is Blocked

```bash
# This should FAIL (port 1883 not exposed)
telnet localhost 1883
# or
nc localhost 1883
```

**Expected:** Connection refused or timeout

### Test 3: Test MQTT Publisher

```powershell
# Set environment variables
$env:MQTT_USERNAME = "your_username"
$env:MQTT_PASSWORD = "your_password"

# Run publisher
python data.py
```

**Expected Output:**
```
TLS configured (CA: ./mosquitto/certs/ca.crt)
Authentication configured (Username: your_username)
Connection successful! (TLS-encrypted)
```

### Test 4: Test MQTT Subscriber

```powershell
# Set environment variables in .env or PowerShell
$env:MQTT_USERNAME = "your_username"
$env:MQTT_PASSWORD = "your_password"

# Run API (includes MQTT subscriber)
python api.py
```

**Expected Output:**
```
Connecting to MQTT broker via TLS localhost:8883...
   CA Certificate: ./mosquitto/certs/ca.crt
   Username: your_username
   TLS Version: 1.2+ (enforced)
MQTT subscriber connected to localhost:8883
```

### Test 5: Verify Anonymous Access is Blocked

```python
# This should FAIL (anonymous access disabled)
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("localhost", 8883)  # No username/password
# Expected: Connection refused or authentication error
```

---

## Troubleshooting

### Issue: "CA certificate not found"

**Solution:**
```powershell
# Verify certificate exists
Test-Path mosquitto/certs/ca.crt

# If missing, regenerate certificates
cd mosquitto
.\generate_certificates.ps1
```

### Issue: "Connection refused" or "Connection timeout"

**Possible Causes:**
1. Broker not running
   ```powershell
   docker-compose up -d
   docker logs mosquitto
   ```

2. Wrong port (using 1883 instead of 8883)
   ```powershell
   # Verify environment variable
   echo $env:MQTT_PORT  # Should be 8883
   ```

3. Firewall blocking port 8883
   ```powershell
   # Check if port is listening
   netstat -an | findstr 8883
   ```

### Issue: "Authentication failed"

**Solution:**
1. Verify username/password in password file:
   ```powershell
   .\setup_password_file.ps1 -List
   ```

2. Verify environment variables:
   ```powershell
   echo $env:MQTT_USERNAME
   echo $env:MQTT_PASSWORD
   ```

3. Recreate password if needed:
   ```powershell
   .\setup_password_file.ps1 -Remove -Username <username>
   .\setup_password_file.ps1 -Add -Username <username>
   ```

### Issue: "Certificate verification failed"

**Solution:**
1. Verify CA certificate path:
   ```powershell
   Test-Path $env:MQTT_CA_CERT
   ```

2. Verify certificate is valid:
   ```bash
   openssl x509 -in mosquitto/certs/ca.crt -text -noout
   ```

3. Ensure client is using correct CA certificate:
   ```python
   # In Python code, verify path
   import os
   print(os.getenv("MQTT_CA_CERT"))
   ```

### Issue: "TLS handshake failed"

**Possible Causes:**
1. Server certificate not signed by CA
   ```bash
   openssl verify -CAfile mosquitto/certs/ca.crt mosquitto/certs/server.crt
   ```

2. Certificate expired (check validity period)
   ```bash
   openssl x509 -in mosquitto/certs/server.crt -noout -dates
   ```

3. Wrong hostname in certificate
   - Update `COMMON_NAME` in certificate generation script
   - Regenerate certificates with correct hostname

---

## Security Audit Checklist

### Configuration Audit

- [ ] Port 1883 (unencrypted) is NOT exposed in docker-compose.yml
- [ ] Port 8883 (TLS) is the ONLY exposed port
- [ ] `allow_anonymous false` in mosquitto.conf
- [ ] `password_file` is configured in mosquitto.conf
- [ ] TLS version is set to `tlsv1.2` or higher
- [ ] CA, server cert, and server key are configured

### Certificate Audit

- [ ] CA certificate (`ca.crt`) exists and is valid
- [ ] Server certificate (`server.crt`) exists and is signed by CA
- [ ] Server private key (`server.key`) has restricted permissions (600)
- [ ] Certificates are not expired
- [ ] Certificate key size is 2048-bit or higher
- [ ] `server.key` is NOT committed to version control

### Authentication Audit

- [ ] Password file (`passwd`) exists
- [ ] Password file has restricted permissions (600)
- [ ] At least one user exists in password file
- [ ] Passwords are hashed (bcrypt), not plaintext
- [ ] Username/password are set in client environment variables

### Network Security Audit

- [ ] Only port 8883 is accessible from outside container
- [ ] TLS 1.2+ is enforced (no fallback to lower versions)
- [ ] Certificate validation is required on clients
- [ ] No plaintext MQTT traffic possible

### Client Security Audit

- [ ] All clients use port 8883 (not 1883)
- [ ] All clients configure TLS with CA certificate
- [ ] All clients use username/password authentication
- [ ] No clients allow anonymous connections
- [ ] Client code rejects insecure connections

### Operational Security Audit

- [ ] Docker container runs with non-root user (if possible)
- [ ] Log files are monitored
- [ ] Certificate expiration is tracked
- [ ] Password file is backed up securely
- [ ] Private keys are stored securely (not in version control)

---

## Security Best Practices

### 1. Certificate Management

- **Rotate certificates** before expiration (recommended: annually)
- **Backup private keys** securely (encrypted, off-site)
- **Monitor certificate expiration** (set calendar reminders)
- **Use separate certificates** for production and development

### 2. Password Management

- **Use strong passwords** (minimum 16 characters, mixed case, numbers, symbols)
- **Rotate passwords** regularly (recommended: quarterly)
- **Limit user accounts** to minimum necessary
- **Remove unused accounts** immediately

### 3. Network Security

- **Use firewall rules** to restrict access to port 8883
- **Monitor network traffic** for anomalies
- **Implement rate limiting** if supported
- **Use VPN** for remote access to broker

### 4. Logging & Monitoring

- **Enable all logging** in mosquitto.conf
- **Monitor log files** for authentication failures
- **Set up alerts** for suspicious activity
- **Retain logs** according to compliance requirements

### 5. Compliance

- **Document all security configurations**
- **Maintain audit trail** of certificate and password changes
- **Regular security reviews** (recommended: quarterly)
- **Penetration testing** (recommended: annually)

---

## Additional Resources

### Mosquitto Documentation
- [Mosquitto TLS Configuration](https://mosquitto.org/man/mosquitto-conf-5.html)
- [Mosquitto Authentication](https://mosquitto.org/documentation/authentication-methods/)

### OpenSSL Documentation
- [OpenSSL Certificate Authority](https://www.openssl.org/docs/man1.1.1/man1/ca.html)
- [OpenSSL Certificate Generation](https://www.openssl.org/docs/man1.1.1/man1/x509.html)

### Healthcare Compliance
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

---

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review Mosquitto logs: `docker logs mosquitto`
3. Verify configuration files match this guide
4. Test with OpenSSL: `openssl s_client -connect localhost:8883 -CAfile mosquitto/certs/ca.crt`

---

**Last Updated:** 2024  
**Security Level:** Production / Healthcare IoT  
**Status:** Fully Secured
