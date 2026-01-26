#!/bin/bash
# ============================================================================
# Healthcare-Grade MQTT Password File Setup Script
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
#   ./setup_password_file.sh -c -u <username>
#
#   # Add additional user to existing file
#   ./setup_password_file.sh -a -u <username>
#
#   # Remove user from password file
#   ./setup_password_file.sh -r -u <username>
#
#   # List all users (hashed passwords)
#   ./setup_password_file.sh -l
#
# PREREQUISITES:
#   - mosquitto_passwd must be available (comes with Mosquitto)
#   - Docker container must have mosquitto_passwd, or use host system
#
# ============================================================================

set -e

PASSWD_FILE="./passwd"
MOSQUITTO_PASSWD="mosquitto_passwd"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if mosquitto_passwd is available
if ! command -v $MOSQUITTO_PASSWD &> /dev/null; then
    echo -e "${RED}ERROR: mosquitto_passwd not found${NC}"
    echo "   Please install Mosquitto or use Docker container:"
    echo "   docker exec -it mosquitto mosquitto_passwd ..."
    exit 1
fi

# Function to create password file
create_password_file() {
    local username=$1
    
    if [ -z "$username" ]; then
        echo -e "${RED}ERROR: Username required${NC}"
        exit 1
    fi
    
    if [ -f "$PASSWD_FILE" ]; then
        echo -e "${YELLOW}Password file already exists: $PASSWD_FILE${NC}"
        read -p "Overwrite? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
        rm -f "$PASSWD_FILE"
    fi
    
    echo -e "${YELLOW}Creating password file: $PASSWD_FILE${NC}"
    echo -e "${YELLOW}Enter password for user '$username':${NC}"
    $MOSQUITTO_PASSWD -c "$PASSWD_FILE" "$username"
    
    # Restrict file permissions (owner read/write only)
    chmod 600 "$PASSWD_FILE"
    
    echo -e "${GREEN}Password file created: $PASSWD_FILE${NC}"
    echo -e "${GREEN}User '$username' added${NC}"
    echo -e "${YELLOW}File permissions set to 600 (owner read/write only)${NC}"
}

# Function to add user to existing password file
add_user() {
    local username=$1
    
    if [ -z "$username" ]; then
        echo -e "${RED}ERROR: Username required${NC}"
        exit 1
    fi
    
    if [ ! -f "$PASSWD_FILE" ]; then
        echo -e "${RED}ERROR: Password file does not exist: $PASSWD_FILE${NC}"
        echo "   Create it first with: $0 -c -u <username>"
        exit 1
    fi
    
    echo -e "${YELLOW}Adding user '$username' to password file...${NC}"
    echo -e "${YELLOW}Enter password for user '$username':${NC}"
    $MOSQUITTO_PASSWD "$PASSWD_FILE" "$username"
    
    # Ensure file permissions are restricted
    chmod 600 "$PASSWD_FILE"
    
    echo -e "${GREEN}User '$username' added${NC}"
}

# Function to remove user from password file
remove_user() {
    local username=$1
    
    if [ -z "$username" ]; then
        echo -e "${RED}ERROR: Username required${NC}"
        exit 1
    fi
    
    if [ ! -f "$PASSWD_FILE" ]; then
        echo -e "${RED}ERROR: Password file does not exist: $PASSWD_FILE${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Removing user '$username' from password file...${NC}"
    $MOSQUITTO_PASSWD -D "$PASSWD_FILE" "$username"
    
    echo -e "${GREEN}User '$username' removed${NC}"
}

# Function to list users
list_users() {
    if [ ! -f "$PASSWD_FILE" ]; then
        echo -e "${RED}ERROR: Password file does not exist: $PASSWD_FILE${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Users in password file:${NC}"
    echo "----------------------------------------"
    cut -d: -f1 "$PASSWD_FILE" | while read username; do
        echo "  $username"
    done
    echo "----------------------------------------"
    echo -e "${GREEN}Total users: $(wc -l < "$PASSWD_FILE")${NC}"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--create)
            CREATE=true
            shift
            ;;
        -a|--add)
            ADD=true
            shift
            ;;
        -r|--remove)
            REMOVE=true
            shift
            ;;
        -l|--list)
            LIST=true
            shift
            ;;
        -u|--username)
            USERNAME="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -c, --create          Create new password file"
            echo "  -a, --add            Add user to existing file"
            echo "  -r, --remove         Remove user from file"
            echo "  -l, --list           List all users"
            echo "  -u, --username USER  Username (required for -c, -a, -r)"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Execute requested action
if [ "$LIST" = true ]; then
    list_users
elif [ "$CREATE" = true ]; then
    create_password_file "$USERNAME"
elif [ "$ADD" = true ]; then
    add_user "$USERNAME"
elif [ "$REMOVE" = true ]; then
    remove_user "$USERNAME"
else
    echo -e "${RED}ERROR: No action specified${NC}"
    echo "Use -h or --help for usage information"
    exit 1
fi
