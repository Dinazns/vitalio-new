# MQTT Broker Quick Start Guide

## Quick Setup (5 Minutes)

### Step 1: Generate Certificates

**Windows:**
```powershell
cd mosquitto
.\generate_certificates.ps1
```

**Linux/Mac:**
```bash
cd mosquitto
chmod +x generate_certificates.sh
./generate_certificates.sh
```

### Step 2: Create Password File

**Windows:**
```powershell
.\setup_password_file.ps1 -Create -Username admin
```

**Linux/Mac:**
```bash
chmod +x setup_password_file.sh
./setup_password_file.sh -c -u admin
```

### Step 3: Start Broker

```powershell
cd ..
docker-compose up -d
```

### Step 4: Verify Broker is Running

```powershell
docker logs mosquitto
```

You should see:
```
mosquitto version 2.x.x running
```

### Step 5: Test Connection

**Set environment variables:**
```powershell
$env:MQTT_USERNAME = "admin"
$env:MQTT_PASSWORD = "<your_password>"
```

**Test publisher:**
```powershell
python data.py
```

**Test subscriber (in another terminal):**
```powershell
python api.py
```

---

## Common Commands

### Certificate Management
```powershell
# Generate certificates
.\generate_certificates.ps1

# Verify certificates
openssl x509 -in certs/ca.crt -text -noout
```

### Password Management
```powershell
# Create password file
.\setup_password_file.ps1 -Create -Username <username>

# Add user
.\setup_password_file.ps1 -Add -Username <username>

# List users
.\setup_password_file.ps1 -List

# Remove user
.\setup_password_file.ps1 -Remove -Username <username>
```

### Docker Management
```powershell
# Start broker
docker-compose up -d

# Stop broker
docker-compose down

# View logs
docker logs mosquitto

# Restart broker
docker-compose restart
```

### Testing
```powershell
# Test TLS connection
openssl s_client -connect localhost:8883 -CAfile certs/ca.crt

# Verify port 1883 is blocked (should fail)
telnet localhost 1883
```

---

## Security Checklist

- [ ] Certificates generated (`ca.crt`, `server.crt`, `server.key`)
- [ ] Password file created (`passwd`)
- [ ] Port 8883 only (1883 disabled)
- [ ] Anonymous access disabled
- [ ] TLS 1.2+ enforced
- [ ] Environment variables set (MQTT_USERNAME, MQTT_PASSWORD)

---

## Full Documentation

See [MQTT_SECURITY_GUIDE.md](../MQTT_SECURITY_GUIDE.md) for complete documentation.

---

## Troubleshooting

**"CA certificate not found"**
→ Run `.\generate_certificates.ps1`

**"Connection refused"**
→ Check `docker-compose up -d` and `docker logs mosquitto`

**"Authentication failed"**
→ Verify username/password with `.\setup_password_file.ps1 -List`

**"Certificate verification failed"**
→ Ensure `MQTT_CA_CERT` environment variable points to `./mosquitto/certs/ca.crt`
