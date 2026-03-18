// Auth0 roles and permissions helpers. Roles/permissions from ID or access token claims.

export const ROLES_CLAIM = 'https://vitalio.app/roles';
export const PERMISSIONS_CLAIM = 'permissions';
/** Auth0 role "Superuser" (Médecin). Match exact casing from Auth0. */
export const DOCTOR_ROLE = 'Superuser';
export const DOCTOR_PERMISSION = 'read:medical_data';

/**
 * Extract roles array from Auth0 user / token claims.
 * @param {object} source - Auth0 user or decoded token payload
 * @returns {string[]}
 */
export function getRoles(source) {
  if (!source) return [];
  const claim = source[ROLES_CLAIM] ?? source['roles'];
  return Array.isArray(claim) ? claim : [];
}

/**
 * Extract permissions array from Auth0 user / token claims.
 * Also checks "scope" (space-separated) when "permissions" is missing.
 * @param {object} source - Auth0 user or decoded token payload
 * @returns {string[]}
 */
export function getPermissions(source) {
  if (!source) return [];
  const claim = source[PERMISSIONS_CLAIM] ?? source['https://vitalio.app/permissions'];
  if (Array.isArray(claim)) return claim;
  const scope = source.scope;
  if (typeof scope === 'string') return scope.trim().split(/\s+/).filter(Boolean);
  return [];
}

/**
 * Check if user has a specific role.
 * @param {object} source - Auth0 user or decoded token
 * @param {string} role - Role to check (e.g. 'superuser')
 * @returns {boolean}
 */
export function hasRole(source, role) {
  if (!role) return false;
  return getRoles(source).includes(role);
}

/**
 * Check if user has a specific permission.
 * @param {object} source - Auth0 user or decoded token
 * @param {string} permission - Permission to check (e.g. 'read:medical_data')
 * @returns {boolean}
 */
export function hasPermission(source, permission) {
  if (!permission) return false;
  return getPermissions(source).includes(permission);
}

/**
 * Check if user has at least one of the required roles.
 * @param {object} source - Auth0 user or decoded token
 * @param {string[]} roles - List of acceptable roles
 * @returns {boolean}
 */
export function hasAnyRole(source, roles = []) {
  if (!roles || roles.length === 0) return true;
  const userRoles = getRoles(source);
  return roles.some((r) => userRoles.includes(r));
}

/**
 * Doctor = superuser role AND read:medical_data permission.
 * @param {object} rolesSource - User or decoded ID token (for roles)
 * @param {object|null} permSource - User or decoded access token (for permissions)
 * @returns {boolean}
 */
export function isDoctor(rolesSource, permSource) {
  const p = permSource ?? rolesSource;
  return hasRole(rolesSource, DOCTOR_ROLE) && hasPermission(p, DOCTOR_PERMISSION);
}

/**
 * Decode JWT payload (no verification). Use to read roles/permissions from access token.
 * @param {string} token - Raw JWT
 * @returns {object|null}
 */
export function decodeJwtPayload(token) {
  if (!token || typeof token !== 'string') return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch {
    return null;
  }
}

