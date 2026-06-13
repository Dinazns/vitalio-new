# Guide de Vérification de la Configuration TLS MQTT

## Vue d'ensemble

Ce guide permet de vérifier que le broker MQTT est correctement configuré avec TLS et les certificats X.509 pour garantir la **confidentialité**, l'**authenticité** et l'**intégrité** des communications.

---

## Vérification Rapide

### Script Automatique (Recommandé)

**Windows PowerShell:**
```powershell
cd mosquitto
.\verify_tls_setup.ps1
```

Le script vérifie automatiquement:
- ✅ Présence des certificats (ca.crt, server.crt, server.key)
- ✅ Validité des certificats
- ✅ Signature du certificat serveur par le CA
- ✅ Configuration Mosquitto (port 8883, TLS, accès anonyme désactivé)
- ✅ Configuration Docker (ports exposés, volumes)
- ✅ Fichier de mots de passe

---

## Vérification Manuelle

### 1. Vérifier les Certificats

Les certificats doivent être dans `mosquitto/certs/`:

```powershell
# Vérifier la présence des fichiers
Test-Path mosquitto\certs\ca.crt
Test-Path mosquitto\certs\server.crt
Test-Path mosquitto\certs\server.key
```

**Résultat attendu:** `True` pour les trois fichiers

### 2. Vérifier la Validité des Certificats

```powershell
# Vérifier le certificat CA
openssl x509 -in mosquitto\certs\ca.crt -text -noout

# Vérifier le certificat serveur
openssl x509 -in mosquitto\certs\server.crt -text -noout

# Vérifier que le certificat serveur est signé par le CA
openssl verify -CAfile mosquitto\certs\ca.crt mosquitto\certs\server.crt
```

**Résultat attendu:** `mosquitto/certs/server.crt: OK`

### 3. Vérifier la Configuration Mosquitto

```powershell
# Vérifier le port TLS
Select-String -Path mosquitto\mosquitto.conf -Pattern "listener 8883"

# Vérifier que le port 1883 n'est pas configuré
Select-String -Path mosquitto\mosquitto.conf -Pattern "listener 1883"

# Vérifier TLS
Select-String -Path mosquitto\mosquitto.conf -Pattern "tls_version"

# Vérifier l'accès anonyme
Select-String -Path mosquitto\mosquitto.conf -Pattern "allow_anonymous"
```

**Résultats attendus:**
- `listener 8883` → **Trouvé**
- `listener 1883` → **Non trouvé**
- `tls_version tlsv1.2` → **Trouvé**
- `allow_anonymous false` → **Trouvé**

### 4. Vérifier Docker Compose

```powershell
# Vérifier les ports exposés
Select-String -Path docker-compose.yml -Pattern "8883:8883"
Select-String -Path docker-compose.yml -Pattern "1883:1883"

# Vérifier le montage des certificats
Select-String -Path docker-compose.yml -Pattern "mosquitto/certs"
```

**Résultats attendus:**
- `8883:8883` → **Trouvé**
- `1883:1883` → **Non trouvé**
- `mosquitto/certs:/mosquitto/certs` → **Trouvé**

### 5. Vérifier le Fichier de Mots de Passe

```powershell
# Vérifier la présence
Test-Path mosquitto\passwd

# Lister les utilisateurs (si présent)
if (Test-Path mosquitto\passwd) {
    Get-Content mosquitto\passwd | ForEach-Object { $_.Split(':')[0] }
}
```

---

## Test de Connexion TLS

### 1. Démarrer le Broker

```powershell
docker-compose up -d
docker logs mosquitto
```

**Vérifier dans les logs:**
- `mosquitto version` → Broker démarré
- `Opening ipv4 listen socket on port 8883` → Port TLS actif
- **Aucune mention du port 1883**

### 2. Tester la Connexion TLS

```powershell
# Test avec OpenSSL
openssl s_client -connect localhost:8883 -CAfile mosquitto\certs\ca.crt
```

**Résultat attendu:**
```
Verify return code: 0 (ok)
Protocol  : TLSv1.2 ou TLSv1.3
```

### 3. Vérifier que le Port 1883 est Bloqué

```powershell
# Ceci devrait échouer (connexion refusée)
Test-NetConnection -ComputerName localhost -Port 1883
```

**Résultat attendu:** `TcpTestSucceeded: False`

### 4. Tester avec un Client MQTT

**Configurer les variables d'environnement:**
```powershell
$env:MQTT_USERNAME = "votre_username"
$env:MQTT_PASSWORD = "votre_password"
$env:MQTT_CA_CERT = ".\mosquitto\certs\ca.crt"
```

**Tester le publisher:**
```powershell
python data.py
```

**Résultat attendu:**
```
✅ TLS configured (CA: ./mosquitto/certs/ca.crt)
✅ Authentication configured (Username: votre_username)
✅ Connection successful! (TLS-encrypted)
```

---

## Checklist de Sécurité

### Certificats X.509
- [ ] `ca.crt` présent dans `mosquitto/certs/`
- [ ] `server.crt` présent dans `mosquitto/certs/`
- [ ] `server.key` présent dans `mosquitto/certs/`
- [ ] Certificats valides (non expirés)
- [ ] Certificat serveur signé par le CA
- [ ] Permissions de `server.key` restreintes (600)

### Configuration Mosquitto
- [ ] Port 8883 (TLS) configuré
- [ ] Port 1883 (non sécurisé) **NON** configuré
- [ ] TLS 1.2+ configuré
- [ ] Accès anonyme désactivé (`allow_anonymous false`)
- [ ] Certificats configurés (cafile, certfile, keyfile)
- [ ] Fichier de mots de passe configuré

### Docker
- [ ] Port 8883 exposé
- [ ] Port 1883 **NON** exposé
- [ ] Volume des certificats monté
- [ ] Volume du fichier de mots de passe monté

### Authentification
- [ ] Fichier `passwd` créé
- [ ] Au moins un utilisateur configuré
- [ ] Variables d'environnement MQTT_USERNAME et MQTT_PASSWORD définies

### Tests
- [ ] Broker démarre sans erreur
- [ ] Connexion TLS réussie (OpenSSL)
- [ ] Port 1883 bloqué/inaccessible
- [ ] Client MQTT Python se connecte avec TLS
- [ ] Messages publiés et reçus avec succès

---

## Garanties de Sécurité

### Confidentialité ✅
- **TLS 1.2+** chiffre toutes les communications MQTT
- **Aucun trafic en clair** sur le réseau
- **Certificats X.509** pour l'authentification mutuelle

### Authenticité ✅
- **Certificat serveur** signé par le CA (broker authentifié)
- **Certificat CA** utilisé par les clients pour vérifier le broker
- **Username/password** pour l'authentification des clients
- **Accès anonyme désactivé**

### Intégrité ✅
- **TLS** garantit l'intégrité des messages (détection de modification)
- **Certificats valides** et non expirés
- **Signature du certificat serveur** vérifiée par le CA

---

## Dépannage

### Problème: "CA certificate not found"

**Solution:**
```powershell
# Vérifier que le fichier existe
Test-Path mosquitto\certs\ca.crt

# Si absent, placer le certificat CA dans mosquitto\certs\
```

### Problème: "Certificate verification failed"

**Solution:**
```powershell
# Vérifier que le certificat serveur est signé par le CA
openssl verify -CAfile mosquitto\certs\ca.crt mosquitto\certs\server.crt

# Si échec, régénérer les certificats ou vérifier la chaîne de certificats
```

### Problème: "Connection refused" sur le port 8883

**Solution:**
```powershell
# Vérifier que le broker est démarré
docker ps | Select-String mosquitto

# Vérifier les logs
docker logs mosquitto

# Redémarrer si nécessaire
docker-compose restart
```

### Problème: "Authentication failed"

**Solution:**
```powershell
# Vérifier le fichier de mots de passe
Test-Path mosquitto\passwd

# Vérifier les variables d'environnement
echo $env:MQTT_USERNAME
echo $env:MQTT_PASSWORD

# Recréer le mot de passe si nécessaire
.\setup_password_file.ps1 -Remove -Username <username>
.\setup_password_file.ps1 -Add -Username <username>
```

---

## Support

Pour plus d'informations, consultez:
- `QUICK_START.md` - Guide de démarrage rapide
- Scripts de génération de certificats dans `mosquitto/`
- Scripts de gestion des mots de passe dans `mosquitto/`

---

**Dernière mise à jour:** 2024  
**Niveau de sécurité:** Production / Healthcare IoT  
**Statut:** ✅ Configuration TLS complète
