from google.cloud import storage
import os

BUCKET_NAME = "assignment_alter"

def upload_to_gcp(file_path, destination_blob_name):
    """Uploads a file to Google Cloud Storage."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(file_path)
    os.remove(file_path)  # Remove local file after upload
    return f"File {destination_blob_name} uploaded to {BUCKET_NAME}"
