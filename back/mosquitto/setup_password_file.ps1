# ============================================================================
# Healthcare-Grade MQTT Password File Setup Script (PowerShell)
# Creates and manages username/password authentication for Mosquitto
# ============================================================================
#
# SECURITY NOTES:
# - Passwords are hashed using bcrypt (not stored in plaintext)
# - File permissions are restricted (owner read/write only)
# - Anonymous access is disabled in mosquitto.conf
#
# USAGE:
#   # Create new password file with first user
#   .\setup_password_file.ps1 -Create -Username <username>
#
#   # Add additional user to existing file
#   .\setup_password_file.ps1 -Add -Username <username>
#
#   # Remove user from password file
#   .\setup_password_file.ps1 -Remove -Username <username>
#
#   # List all users
#   .\setup_password_file.ps1 -List
#
# PREREQUISITES:
#   - Mosquitto Docker container must be running
#   - Or mosquitto_passwd installed on host system
#
# ============================================================================

param(
    [switch]$Create,
    [switch]$Add,
    [switch]$Remove,
    [switch]$List,
    [string]$Username = "",
    [string]$DockerContainer = "mosquitto"
)

$ErrorActionPreference = "Stop"

$PASSWD_FILE = ".\passwd"
$USE_DOCKER = $false

# Check if running in Docker or using host mosquitto_passwd
$mosquittoPasswdCmd = "mosquitto_passwd"
try {
    $null = Get-Command mosquitto_passwd -ErrorAction Stop
    $USE_DOCKER = $false
} catch {
    # Try Docker
    try {
        $null = docker ps --filter "name=$DockerContainer" --format "{{.Names}}"
        $USE_DOCKER = $true
        $mosquittoPasswdCmd = "docker exec -i $DockerContainer mosquitto_passwd"
    } catch {
        Write-Host "ERROR: mosquitto_passwd not found and Docker container '$DockerContainer' not running" -ForegroundColor Red
        Write-Host "   Please either:" -ForegroundColor Yellow
        Write-Host "   1. Install Mosquitto on host system, or" -ForegroundColor Yellow
        Write-Host "   2. Start Docker container: docker-compose up -d" -ForegroundColor Yellow
        exit 1
    }
}

function Create-PasswordFile {
    param([string]$Username)
    
    if ([string]::IsNullOrEmpty($Username)) {
        Write-Host "ERROR: Username required" -ForegroundColor Red
        exit 1
    }
    
    if (Test-Path $PASSWD_FILE) {
        Write-Host "Password file already exists: $PASSWD_FILE" -ForegroundColor Yellow
        $response = Read-Host "Overwrite? (y/N)"
        if ($response -ne "y" -and $response -ne "Y") {
            Write-Host "Aborted." -ForegroundColor Yellow
            exit 1
        }
        Remove-Item $PASSWD_FILE -Force
    }
    
    Write-Host "Creating password file: $PASSWD_FILE" -ForegroundColor Yellow
    Write-Host "Enter password for user '$Username':" -ForegroundColor Yellow
    
    if ($USE_DOCKER) {
        $password = Read-Host -AsSecureString
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
        $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
        
        # Create password file via Docker
        docker exec -i $DockerContainer sh -c "echo '$plainPassword' | mosquitto_passwd -c /mosquitto/passwd $Username"
        docker cp "${DockerContainer}:/mosquitto/passwd" $PASSWD_FILE
    } else {
        # Use host mosquitto_passwd
        & mosquitto_passwd -c $PASSWD_FILE $Username
    }
    
    # Restrict file permissions (owner read/write only)
    icacls $PASSWD_FILE /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    
    Write-Host "Password file created: $PASSWD_FILE" -ForegroundColor Green
    Write-Host "User '$Username' added" -ForegroundColor Green
    Write-Host "File permissions set to owner read/write only" -ForegroundColor Yellow
}

function Add-User {
    param([string]$Username)
    
    if ([string]::IsNullOrEmpty($Username)) {
        Write-Host "ERROR: Username required" -ForegroundColor Red
        exit 1
    }
    
    if (-not (Test-Path $PASSWD_FILE)) {
        Write-Host "ERROR: Password file does not exist: $PASSWD_FILE" -ForegroundColor Red
        Write-Host "   Create it first with: .\setup_password_file.ps1 -Create -Username <username>" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "Adding user '$Username' to password file..." -ForegroundColor Yellow
    Write-Host "Enter password for user '$Username':" -ForegroundColor Yellow
    
    if ($USE_DOCKER) {
        # Copy password file to container temporarily
        docker cp $PASSWD_FILE "${DockerContainer}:/mosquitto/passwd"
        
        $password = Read-Host -AsSecureString
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
        $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
        
        docker exec -i $DockerContainer sh -c "echo '$plainPassword' | mosquitto_passwd /mosquitto/passwd $Username"
        docker cp "${DockerContainer}:/mosquitto/passwd" $PASSWD_FILE
    } else {
        & mosquitto_passwd $PASSWD_FILE $Username
    }
    
    # Ensure file permissions are restricted
    icacls $PASSWD_FILE /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    
    Write-Host "User '$Username' added" -ForegroundColor Green
}

function Remove-User {
    param([string]$Username)
    
    if ([string]::IsNullOrEmpty($Username)) {
        Write-Host "ERROR: Username required" -ForegroundColor Red
        exit 1
    }
    
    if (-not (Test-Path $PASSWD_FILE)) {
        Write-Host "ERROR: Password file does not exist: $PASSWD_FILE" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "Removing user '$Username' from password file..." -ForegroundColor Yellow
    
    if ($USE_DOCKER) {
        docker cp $PASSWD_FILE "${DockerContainer}:/mosquitto/passwd"
        docker exec $DockerContainer mosquitto_passwd -D /mosquitto/passwd $Username
        docker cp "${DockerContainer}:/mosquitto/passwd" $PASSWD_FILE
    } else {
        & mosquitto_passwd -D $PASSWD_FILE $Username
    }
    
    Write-Host "User '$Username' removed" -ForegroundColor Green
}

function List-Users {
    if (-not (Test-Path $PASSWD_FILE)) {
        Write-Host "ERROR: Password file does not exist: $PASSWD_FILE" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "Users in password file:" -ForegroundColor Yellow
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    $users = Get-Content $PASSWD_FILE | ForEach-Object {
        $_.Split(':')[0]
    }
    foreach ($user in $users) {
        Write-Host "  $user" -ForegroundColor White
    }
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "Total users: $($users.Count)" -ForegroundColor Green
}

# Execute requested action
if ($List) {
    List-Users
} elseif ($Create) {
    Create-PasswordFile -Username $Username
} elseif ($Add) {
    Add-User -Username $Username
} elseif ($Remove) {
    Remove-User -Username $Username
} else {
    Write-Host "ERROR: No action specified" -ForegroundColor Red
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\setup_password_file.ps1 -Create -Username <username>" -ForegroundColor White
    Write-Host "  .\setup_password_file.ps1 -Add -Username <username>" -ForegroundColor White
    Write-Host "  .\setup_password_file.ps1 -Remove -Username <username>" -ForegroundColor White
    Write-Host "  .\setup_password_file.ps1 -List" -ForegroundColor White
    exit 1
}
