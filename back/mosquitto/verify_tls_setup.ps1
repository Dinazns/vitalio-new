# ============================================================================
# Script de Vérification de la Configuration TLS MQTT
# Vérifie que tous les éléments de sécurité sont correctement configurés
# ============================================================================

$ErrorActionPreference = "Continue"

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Vérification de la Configuration TLS MQTT" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

$allChecksPassed = $true
$CERT_DIR = ".\certs"

# ============================================================================
# VÉRIFICATION 1: Certificats X.509
# ============================================================================
Write-Host "1. Vérification des certificats X.509..." -ForegroundColor Yellow
Write-Host ""

$requiredCerts = @("ca.crt", "server.crt", "server.key")
$missingCerts = @()

foreach ($cert in $requiredCerts) {
    $certPath = Join-Path $CERT_DIR $cert
    if (Test-Path $certPath) {
        $fileInfo = Get-Item $certPath
        Write-Host "  [OK] $cert trouvé ($($fileInfo.Length) bytes)" -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] $cert manquant dans $CERT_DIR" -ForegroundColor Red
        $missingCerts += $cert
        $allChecksPassed = $false
    }
}

if ($missingCerts.Count -gt 0) {
    Write-Host ""
    Write-Host "  Les certificats suivants sont manquants:" -ForegroundColor Red
    foreach ($cert in $missingCerts) {
        Write-Host "    - $cert" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "  Solution: Placez les certificats dans $CERT_DIR\" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "  Tous les certificats requis sont présents." -ForegroundColor Green
}

Write-Host ""

# ============================================================================
# VÉRIFICATION 2: Validité des certificats
# ============================================================================
Write-Host "2. Vérification de la validité des certificats..." -ForegroundColor Yellow
Write-Host ""

$opensslPath = Get-Command openssl -ErrorAction SilentlyContinue
if ($opensslPath) {
    # Vérifier le certificat CA
    $caCertPath = Join-Path $CERT_DIR "ca.crt"
    if (Test-Path $caCertPath) {
        try {
            $caInfo = & openssl x509 -in $caCertPath -noout -subject -dates 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] Certificat CA valide" -ForegroundColor Green
                $caInfo | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }
            } else {
                Write-Host "  [ERREUR] Certificat CA invalide" -ForegroundColor Red
                $allChecksPassed = $false
            }
        } catch {
            Write-Host "  [AVERTISSEMENT] Impossible de vérifier le certificat CA" -ForegroundColor Yellow
        }
    }
    
    # Vérifier le certificat serveur
    $serverCertPath = Join-Path $CERT_DIR "server.crt"
    if (Test-Path $serverCertPath) {
        try {
            $serverInfo = & openssl x509 -in $serverCertPath -noout -subject -dates 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] Certificat serveur valide" -ForegroundColor Green
                $serverInfo | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }
            } else {
                Write-Host "  [ERREUR] Certificat serveur invalide" -ForegroundColor Red
                $allChecksPassed = $false
            }
        } catch {
            Write-Host "  [AVERTISSEMENT] Impossible de vérifier le certificat serveur" -ForegroundColor Yellow
        }
    }
    
    # Vérifier que le certificat serveur est signé par le CA
    if ((Test-Path $caCertPath) -and (Test-Path $serverCertPath)) {
        try {
            $verifyResult = & openssl verify -CAfile $caCertPath $serverCertPath 2>&1
            if ($LASTEXITCODE -eq 0 -and $verifyResult -match "OK") {
                Write-Host "  [OK] Certificat serveur signé par le CA" -ForegroundColor Green
            } else {
                Write-Host "  [ERREUR] Le certificat serveur n'est pas signé par le CA" -ForegroundColor Red
                $allChecksPassed = $false
            }
        } catch {
            Write-Host "  [AVERTISSEMENT] Impossible de vérifier la signature" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  [AVERTISSEMENT] OpenSSL non trouvé - impossible de vérifier la validité" -ForegroundColor Yellow
    Write-Host "      Installez OpenSSL pour une vérification complète" -ForegroundColor Yellow
}

Write-Host ""

# ============================================================================
# VÉRIFICATION 3: Permissions des fichiers
# ============================================================================
Write-Host "3. Vérification des permissions des fichiers..." -ForegroundColor Yellow
Write-Host ""

$serverKeyPath = Join-Path $CERT_DIR "server.key"
if (Test-Path $serverKeyPath) {
    $acl = Get-Acl $serverKeyPath
    $hasRestrictedAccess = $true
    
    foreach ($access in $acl.Access) {
        if ($access.IdentityReference -ne $env:USERNAME -and 
            $access.FileSystemRights -match "FullControl|Write|Modify") {
            $hasRestrictedAccess = $false
            break
        }
    }
    
    if ($hasRestrictedAccess) {
        Write-Host "  [OK] Permissions du fichier server.key restreintes" -ForegroundColor Green
    } else {
        Write-Host "  [AVERTISSEMENT] Les permissions de server.key devraient être restreintes" -ForegroundColor Yellow
        Write-Host "      Recommandation: icacls $serverKeyPath /inheritance:r /grant:r `"${env:USERNAME}:F`"" -ForegroundColor Gray
    }
} else {
    Write-Host "  [SKIP] server.key non trouvé" -ForegroundColor Gray
}

Write-Host ""

# ============================================================================
# VÉRIFICATION 4: Configuration Mosquitto
# ============================================================================
Write-Host "4. Vérification de la configuration Mosquitto..." -ForegroundColor Yellow
Write-Host ""

$configPath = ".\mosquitto.conf"
if (Test-Path $configPath) {
    $configContent = Get-Content $configPath -Raw
    
    # Vérifier le port TLS
    if ($configContent -match "listener\s+8883") {
        Write-Host "  [OK] Port TLS 8883 configuré" -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] Port TLS 8883 non configuré" -ForegroundColor Red
        $allChecksPassed = $false
    }
    
    # Vérifier que le port 1883 n'est pas configuré
    if ($configContent -match "listener\s+1883") {
        Write-Host "  [ERREUR] Port non sécurisé 1883 trouvé dans la configuration" -ForegroundColor Red
        $allChecksPassed = $false
    } else {
        Write-Host "  [OK] Port non sécurisé 1883 désactivé" -ForegroundColor Green
    }
    
    # Vérifier TLS
    if ($configContent -match "tls_version\s+tlsv1\.2") {
        Write-Host "  [OK] TLS 1.2+ configuré" -ForegroundColor Green
    } else {
        Write-Host "  [AVERTISSEMENT] Version TLS non spécifiée ou incorrecte" -ForegroundColor Yellow
    }
    
    # Vérifier l'accès anonyme
    if ($configContent -match "allow_anonymous\s+false") {
        Write-Host "  [OK] Accès anonyme désactivé" -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] Accès anonyme activé - DANGEREUX!" -ForegroundColor Red
        $allChecksPassed = $false
    }
    
    # Vérifier les certificats dans la config
    if ($configContent -match "cafile\s+/mosquitto/certs/ca\.crt" -and
        $configContent -match "certfile\s+/mosquitto/certs/server\.crt" -and
        $configContent -match "keyfile\s+/mosquitto/certs/server\.key") {
        Write-Host "  [OK] Certificats configurés dans mosquitto.conf" -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] Certificats non configurés correctement" -ForegroundColor Red
        $allChecksPassed = $false
    }
} else {
    Write-Host "  [ERREUR] Fichier mosquitto.conf non trouvé" -ForegroundColor Red
    $allChecksPassed = $false
}

Write-Host ""

# ============================================================================
# VÉRIFICATION 5: Docker Compose
# ============================================================================
Write-Host "5. Vérification de docker-compose.yml..." -ForegroundColor Yellow
Write-Host ""

$dockerComposePath = "..\docker-compose.yml"
if (Test-Path $dockerComposePath) {
    $dockerContent = Get-Content $dockerComposePath -Raw
    
    # Vérifier le port 8883
    if ($dockerContent -match '8883:8883') {
        Write-Host "  [OK] Port TLS 8883 exposé dans Docker" -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] Port TLS 8883 non exposé" -ForegroundColor Red
        $allChecksPassed = $false
    }
    
    # Vérifier que le port 1883 n'est pas exposé
    if ($dockerContent -match '1883:1883') {
        Write-Host "  [ERREUR] Port non sécurisé 1883 exposé dans Docker" -ForegroundColor Red
        $allChecksPassed = $false
    } else {
        Write-Host "  [OK] Port non sécurisé 1883 non exposé" -ForegroundColor Green
    }
    
    # Vérifier le montage des certificats
    if ($dockerContent -match 'mosquitto/certs:/mosquitto/certs') {
        Write-Host "  [OK] Volume des certificats monté" -ForegroundColor Green
    } else {
        Write-Host "  [AVERTISSEMENT] Volume des certificats non monté" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [AVERTISSEMENT] docker-compose.yml non trouvé" -ForegroundColor Yellow
}

Write-Host ""

# ============================================================================
# VÉRIFICATION 6: Fichier de mots de passe
# ============================================================================
Write-Host "6. Vérification du fichier de mots de passe..." -ForegroundColor Yellow
Write-Host ""

$passwdPath = ".\passwd"
if (Test-Path $passwdPath) {
    $userCount = (Get-Content $passwdPath | Measure-Object -Line).Lines
    if ($userCount -gt 0) {
        Write-Host "  [OK] Fichier passwd trouvé avec $userCount utilisateur(s)" -ForegroundColor Green
    } else {
        Write-Host "  [AVERTISSEMENT] Fichier passwd vide" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [AVERTISSEMENT] Fichier passwd non trouvé" -ForegroundColor Yellow
    Write-Host "      Créez-le avec: .\setup_password_file.ps1 -Create -Username <username>" -ForegroundColor Gray
}

Write-Host ""

# ============================================================================
# RÉSUMÉ
# ============================================================================
Write-Host "============================================================================" -ForegroundColor Cyan
if ($allChecksPassed) {
    Write-Host "RÉSULTAT: Configuration TLS correcte!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Prochaines étapes:" -ForegroundColor Yellow
    Write-Host "  1. Démarrer le broker: docker-compose up -d" -ForegroundColor White
    Write-Host "  2. Vérifier les logs: docker logs mosquitto" -ForegroundColor White
    Write-Host "  3. Tester la connexion TLS:" -ForegroundColor White
    Write-Host "     openssl s_client -connect localhost:8883 -CAfile certs\ca.crt" -ForegroundColor Gray
} else {
    Write-Host "RÉSULTAT: Des problèmes ont été détectés!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Veuillez corriger les erreurs ci-dessus avant de démarrer le broker." -ForegroundColor Yellow
}
Write-Host "============================================================================" -ForegroundColor Cyan

exit $(if ($allChecksPassed) { 0 } else { 1 })
