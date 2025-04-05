from pymongo import MongoClient, UpdateOne
import pandas as pd
from google.cloud import secretmanager, storage
import functions_framework
from openai import OpenAI
import os
import json

# Constants
PROJECT_ID = 'Project_Name'
BUCKET_TMP_PATH = "/tmp/"
ALLOWED_COHORTS = {"Sports", "Technology", "Finance", "Entertainment", "Fashion", "Politics", "Food", "Health", "Education"}

# Get secrets
def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

# MongoDB and OpenAI clients
mongo_client = MongoClient(get_secret("Secret_name"))
users_collection = mongo_client.Assignment.alter
openai_client = OpenAI(api_key=get_secret("Secret_Name"))

# Classify interest into cohort
def classify_interest(interest):
    prompt = (
        f"Classify the following interest into a user cohort: {interest}.\n\n"
        f"Examples:\n- Tom Brady -> Sports\n- Nike shoes -> Fashion\n- Bitcoin -> Finance\n\n"
        f"Respond with just one cohort from: {', '.join(ALLOWED_COHORTS)}.\n"
        f"If it doesn't fit, respond with 'unknown'."
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert in user segmentation."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error classifying interest: {interest}, error: {e}")
        return "unknown"

# Function to clean record before insert/update
def clean_record(data):
    return {k: v for k, v in data.items() if isinstance(v, list) or pd.notnull(v)}

# Merge list columns
def merge_lists(row, col_x, col_y):
    merged = []
    for col in [col_x, col_y]:
        if isinstance(row[col], list):
            merged.extend(row[col])
    return list(set(merged)) if merged else None

@functions_framework.http
def hello_http(request):
    event = request.get_json()
    print("Received event:", event)

    bucket_name = event["bucket"]
    file_name = event["name"]
    file_path = os.path.join(BUCKET_TMP_PATH, os.path.basename(file_name))

    if not file_name.endswith((".csv", ".json")):
        return f"Unsupported file type: {file_name}", 400

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        bucket.blob(file_name).download_to_filename(file_path)
        print(f"Downloaded {file_name} to {file_path}")

        user_file = pd.read_csv(file_path) if file_name.endswith(".csv") else pd.read_json(file_path)
    except Exception as e:
        print(f"Failed to load file: {e}")
        return "Failed to load file", 500

    existing_users_df = pd.DataFrame(list(users_collection.find()))

    def interests_formating(interests):
        if pd.notna(interests):
            return [interest.strip() for interest in interests.split('|')]
        else:
            None
    user_file['interests']=user_file['interests'].apply(interests_formating)

    # Classify unique interests
    unique_interests = {interest for sublist in user_file['interests'].dropna() for interest in sublist}
    interest_to_cohort = {interest: classify_interest(interest) for interest in unique_interests}

    # Apply cohorts
    user_file['cohort'] = user_file['interests'].apply(
        lambda lst: list({interest_to_cohort.get(i, "unknown") for i in lst}) if isinstance(lst, list) else None
    )

    # Remove records with duplicate cookies
    user_file = user_file[~user_file['cookie'].isin(existing_users_df['cookie'])]

    # Identify and insert new users (by email)
    new_emails = pd.merge(existing_users_df, user_file.dropna(subset=['email']), on='email', how='inner')['email']
    new_records = user_file[~user_file['email'].isin(new_emails)]
    if not new_records.empty:
        users_collection.insert_many([clean_record(rec) for rec in new_records.to_dict('records')])

    # Merge existing user records
    merged_df = pd.merge(
        existing_users_df.dropna(subset=['email'])[['email', '_id', 'interests', 'cohort']],
        user_file,
        on='email',
        how='inner'
    )

    if merged_df.empty:
        return "No records to merge", 200

    merged_df['interests'] = merged_df.apply(lambda row: merge_lists(row, 'interests_x', 'interests_y'), axis=1)
    merged_df['cohort'] = merged_df.apply(lambda row: merge_lists(row, 'cohort_x', 'cohort_y'), axis=1)
    merged_df['created_at'] = pd.to_datetime(merged_df['created_at'])
    merged_df.drop(columns=['interests_x', 'interests_y', 'cohort_x', 'cohort_y'], inplace=True)

    # Prepare updates
    updates = []
    for rec in merged_df.to_dict('records'):
        _id = rec.pop('_id')
        updates.append(UpdateOne({'_id': _id}, {'$set': clean_record(rec)}))

    if updates:
        users_collection.bulk_write(updates)

    return "Records processed successfully", 200
