from pymongo import MongoClient

client = MongoClient(
    "mongodb://mongodb:27017"
)

db = client["simple_lms"]

activity_logs = db["activity_logs"]

learning_analytics = db["learning_analytics"]