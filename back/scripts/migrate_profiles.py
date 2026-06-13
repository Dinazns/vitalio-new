"""
One-time migration: flag users whose display_name looks like a raw Auth0 user_id
(e.g. "auth0|abc123") so the next login triggers a profile sync via PATCH /api/me/profile.

If AUTH0_MGMT_TOKEN is set, the script also attempts to fetch the real profile data
from the Auth0 Management API and updates MongoDB directly.

Usage:
    python migrate_profiles.py              # flag-only mode (safe, no Auth0 calls)
    python migrate_profiles.py --fetch      # also fetch profiles from Auth0 Mgmt API

Environment variables:
    MONGODB_URI             (default: mongodb://localhost:27017)
    MONGODB_IDENTITY_DB     (default: Vitalio_Identity)
    AUTH0_DOMAIN            (required for --fetch)
    AUTH0_MGMT_TOKEN        (required for --fetch)
"""

importos
importre
importsys
importargparse
fromdatetimeimportdatetime

importrequests
frompymongoimportMongoClient
frompymongo.errorsimportPyMongoError

MONGODB_URI=os.getenv("MONGODB_URI","mongodb://localhost:27017")
MONGODB_IDENTITY_DB=os.getenv("MONGODB_IDENTITY_DB","Vitalio_Identity")
AUTH0_DOMAIN=os.getenv("AUTH0_DOMAIN","")
AUTH0_MGMT_TOKEN=os.getenv("AUTH0_MGMT_TOKEN","")

_AUTH0_ID_RE=re.compile(r"^(auth0|google-oauth2|windowslive|github)\|")

deflooks_like_auth0_id(value:str)->bool:
    returnbool(valueand_AUTH0_ID_RE.match(value)and" "notinvalue)

deffetch_auth0_profile(user_id:str)->dict:
    """Fetch user profile from Auth0 Management API."""
url=f"https://{AUTH0_DOMAIN}/api/v2/users/{requests.utils.quote(user_id,safe='')}"
resp=requests.get(url,headers={"Authorization":f"Bearer {AUTH0_MGMT_TOKEN}"},timeout=10)
resp.raise_for_status()
returnresp.json()

defmain():
    parser=argparse.ArgumentParser(description="Migrate VitalIO user profiles")
parser.add_argument("--fetch",action="store_true",
help="Fetch profiles from Auth0 Management API (requires AUTH0_DOMAIN + AUTH0_MGMT_TOKEN)")
parser.add_argument("--dry-run",action="store_true",
help="Print what would be done without writing to MongoDB")
args=parser.parse_args()

ifargs.fetchand(notAUTH0_DOMAINornotAUTH0_MGMT_TOKEN):
        print("ERROR: --fetch requires AUTH0_DOMAIN and AUTH0_MGMT_TOKEN environment variables.")
sys.exit(1)

client=MongoClient(MONGODB_URI,serverSelectionTimeoutMS=5000)
db=client[MONGODB_IDENTITY_DB]
users=db.users

query={"$or":[
{"display_name":{"$regex":r"^(auth0|google-oauth2|windowslive|github)\|"}},
{"email":{"$in":["",None]}},
]}
cursor=users.find(query)

total=0
flagged=0
fetched=0
errors=0

fordocincursor:
        total+=1
uid=doc.get("user_id_auth","")
display=doc.get("display_name","")
email=doc.get("email","")

needs_sync=looks_like_auth0_id(display)ornotemail
ifnotneeds_sync:
            continue

print(f"  [{uid}] display_name={display!r}  email={email!r}")

ifargs.fetch:
            try:
                profile=fetch_auth0_profile(uid)
updates={}
ifprofile.get("name")andlooks_like_auth0_id(display):
                    updates["display_name"]=str(profile["name"])[:128]
ifprofile.get("email")andnotemail:
                    updates["email"]=str(profile["email"])[:256]
ifprofile.get("given_name"):
                    updates["first_name"]=str(profile["given_name"])[:64]
ifprofile.get("family_name"):
                    updates["last_name"]=str(profile["family_name"])[:64]
ifprofile.get("picture"):
                    updates["picture"]=str(profile["picture"])[:512]

ifupdates:
                    updates["updated_at"]=datetime.utcnow()
ifargs.dry_run:
                        print(f"    [DRY-RUN] Would update: {updates}")
else:
                        users.update_one({"_id":doc["_id"]},{"$set":updates})
print(f"    Updated from Auth0: {list(updates.keys())}")
fetched+=1
else:
                    print(f"    Auth0 profile has no additional data, flagging instead")
ifnotargs.dry_run:
                        users.update_one({"_id":doc["_id"]},{
"$set":{"display_name_pending_sync":True,"updated_at":datetime.utcnow()}
})
flagged+=1

exceptrequests.HTTPErrorase:
                print(f"    Auth0 API error: {e}")
ifnotargs.dry_run:
                    users.update_one({"_id":doc["_id"]},{
"$set":{"display_name_pending_sync":True,"updated_at":datetime.utcnow()}
})
flagged+=1
errors+=1
exceptExceptionase:
                print(f"    Unexpected error: {e}")
errors+=1
else:
            ifargs.dry_run:
                print(f"    [DRY-RUN] Would flag display_name_pending_sync=True")
else:
                users.update_one({"_id":doc["_id"]},{
"$set":{"display_name_pending_sync":True,"updated_at":datetime.utcnow()}
})
flagged+=1

print(f"\nDone. Scanned={total}  Flagged={flagged}  Fetched={fetched}  Errors={errors}")
ifargs.dry_run:
        print("(dry-run mode - no writes were made)")

client.close()

if__name__=="__main__":
    main()
