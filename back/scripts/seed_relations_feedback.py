importos
fromdatetimeimportdatetime,timedelta

fromdotenvimportload_dotenv
frompymongoimportMongoClient
frompymongo.errorsimportPyMongoError

env_path=".env"ifos.path.exists(".env")else"../.env"
load_dotenv(env_path)

MONGODB_URI=os.getenv("MONGODB_URI","mongodb://localhost:27017")
MONGODB_IDENTITY_DB=os.getenv("MONGODB_IDENTITY_DB","Vitalio_Identity")
MONGODB_MEDICAL_DB=os.getenv("MONGODB_MEDICAL_DB","Vitalio_Medical")

SEED_PATIENT_ID_AUTH=os.getenv("SEED_PATIENT_ID_AUTH","auth0|seed-patient")
SEED_DOCTOR_ID_AUTH=os.getenv("SEED_DOCTOR_ID_AUTH","auth0|seed-doctor")
SEED_CAREGIVER_ID_AUTH=os.getenv("SEED_CAREGIVER_ID_AUTH","auth0|seed-caregiver")
SEED_DEVICE_ID=os.getenv("SEED_DEVICE_ID",os.getenv("DEVICE_ID","SIM-ESP32-001"))

defupsert_user(users_collection,user_id_auth:str,role:str,display_name:str,**extra):
    doc={
"user_id_auth":user_id_auth,
"role":role,
"display_name":display_name,
"created_at":datetime.utcnow(),
**extra,
}
users_collection.update_one(
{"user_id_auth":user_id_auth},
{"$set":doc},
upsert=True,
)

defmain():
    try:
        client=MongoClient(MONGODB_URI,serverSelectionTimeoutMS=5000)
client.admin.command("ping")
exceptPyMongoErrorase:
        raiseRuntimeError(f"Cannot connect to MongoDB: {e}")frome

identity_db=client[MONGODB_IDENTITY_DB]
medical_db=client[MONGODB_MEDICAL_DB]

upsert_user(identity_db.users,SEED_PATIENT_ID_AUTH,"patient","Patient Test")
upsert_user(identity_db.users,SEED_DOCTOR_ID_AUTH,"doctor","Docteur Test",
first_name="Sophie",last_name="Martin",email="dr.martin@vitalio.test",contact="dr.martin@vitalio.test")
upsert_user(identity_db.users,SEED_CAREGIVER_ID_AUTH,"caregiver","Aidant Test")

identity_db.users_devices.update_one(
{"user_id_auth":SEED_PATIENT_ID_AUTH},
{"$set":{"user_id_auth":SEED_PATIENT_ID_AUTH,"device_id":SEED_DEVICE_ID}},
upsert=True,
)

identity_db.doctor_patients.update_one(
{
"doctor_user_id_auth":SEED_DOCTOR_ID_AUTH,
"patient_user_id_auth":SEED_PATIENT_ID_AUTH,
},
{
"$set":{
"doctor_user_id_auth":SEED_DOCTOR_ID_AUTH,
"patient_user_id_auth":SEED_PATIENT_ID_AUTH,
},
"$setOnInsert":{"created_at":datetime.utcnow()},
},
upsert=True,
)

identity_db.caregiver_patients.update_one(
{
"caregiver_user_id_auth":SEED_CAREGIVER_ID_AUTH,
"patient_user_id_auth":SEED_PATIENT_ID_AUTH,
},
{
"$set":{
"caregiver_user_id_auth":SEED_CAREGIVER_ID_AUTH,
"patient_user_id_auth":SEED_PATIENT_ID_AUTH,
},
"$setOnInsert":{"created_at":datetime.utcnow()},
},
upsert=True,
)

medical_db.doctor_feedback.insert_one(
{
"patient_user_id_auth":SEED_PATIENT_ID_AUTH,
"doctor_user_id_auth":SEED_DOCTOR_ID_AUTH,
"message":"Surveillance reguliere recommandee, mesurez matin et soir.",
"severity":"medium",
"status":"new",
"recommendation":"Hydratation et suivi de la temperature quotidienne.",
"created_at":datetime.utcnow()-timedelta(minutes=10),
}
)

print("Seed relationnel OK:")
print(f"  patient:   {SEED_PATIENT_ID_AUTH}")
print(f"  doctor:    {SEED_DOCTOR_ID_AUTH}")
print(f"  caregiver: {SEED_CAREGIVER_ID_AUTH}")
print(f"  device_id: {SEED_DEVICE_ID}")

if__name__=="__main__":
    main()
