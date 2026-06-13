exports.onExecutePostLogin = async (event, api) => {
  const NS = "https://vitalio.app/";
  const meta = event.user.user_metadata || {};

  
  const givenName  = meta.given_name  || event.user.given_name  || "";
  const familyName = meta.family_name || event.user.family_name || "";

  api.idToken.setCustomClaim(NS + "given_name",  givenName);
  api.idToken.setCustomClaim(NS + "family_name", familyName);
  api.accessToken.setCustomClaim(NS + "given_name",  givenName);
  api.accessToken.setCustomClaim(NS + "family_name", familyName);

  
  const phoneNumber = meta.phone_number || event.user.phone_number || "";
  const birthdate   = meta.birthdate    || event.user.birthdate    || "";
  const pathology   = meta.pathology    || "";

  api.idToken.setCustomClaim(NS + "phone_number", phoneNumber);
  api.idToken.setCustomClaim(NS + "birthdate",    birthdate);
  api.idToken.setCustomClaim(NS + "pathology",    pathology);
  api.accessToken.setCustomClaim(NS + "phone_number", phoneNumber);
  api.accessToken.setCustomClaim(NS + "birthdate",    birthdate);
  api.accessToken.setCustomClaim(NS + "pathology",    pathology);

  
  const emgLastName  = meta.emergency_lastname  || "";
  const emgFirstName = meta.emergency_firstname || "";
  const emgPhone     = meta.emergency_phone     || "";
  const emgEmail     = meta.emergency_email     || "";

  api.idToken.setCustomClaim(NS + "emergency_lastname",  emgLastName);
  api.idToken.setCustomClaim(NS + "emergency_firstname", emgFirstName);
  api.idToken.setCustomClaim(NS + "emergency_phone",     emgPhone);
  api.idToken.setCustomClaim(NS + "emergency_email",     emgEmail);
  api.accessToken.setCustomClaim(NS + "emergency_lastname",  emgLastName);
  api.accessToken.setCustomClaim(NS + "emergency_firstname", emgFirstName);
  api.accessToken.setCustomClaim(NS + "emergency_phone",     emgPhone);
  api.accessToken.setCustomClaim(NS + "emergency_email",     emgEmail);

  
  let role = (event.user.app_metadata || {}).role || meta.role || "patient";

  
  const rbacRoles = event.user.app_metadata?.authorization?.roles;
  if (Array.isArray(rbacRoles) && rbacRoles.length > 0) {
    role = rbacRoles[0];
  }

  api.idToken.setCustomClaim(NS + "role", role);
  api.accessToken.setCustomClaim(NS + "role", role);
};
