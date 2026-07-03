import os
from pymongo import MongoClient

client = MongoClient(
    os.getenv("MONGODB_URI", "mongodb://mongodb:27017"),
    serverSelectionTimeoutMS=3000,
)

db = client[os.getenv("MONGODB_DB_NAME", "simple_lms")]

activity_logs = db["activity_logs"]

learning_analytics = db["learning_analytics"]