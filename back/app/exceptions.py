"""
Custom exceptions for the VitalIO API.
"""
from typing import Dict


class AuthError(Exception):
    """Custom exception for authentication/authorization errors."""
    def __init__(self, error: Dict[str, str], status_code: int):
        self.error = error
        self.status_code = status_code


class DatabaseError(Exception):
    """Custom exception for database operation errors."""
    def __init__(self, error: Dict[str, str], status_code: int):
        self.error = error
        self.status_code = status_code
