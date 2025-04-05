from flask import Flask, request, jsonify
import pandas as pd
import json
import os
from datetime import datetime
from gcp_utils import upload_to_gcp
from data_utils import validate_data, flatten_json
from pymongo import MongoClient
from google.cloud import secretmanager

app = Flask(__name__)

TEMP_DIR = "/tmp"  # Temporary directory for saving files

# Setup MongoDB from GCP Secret Manager
def get_mongo_client():
    project_id = 'genial-insight-455207-t7'
    secret_id = 'Mongodb'
    version_id = 'latest'
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    connection_string = response.payload.data.decode('UTF-8')
    return MongoClient(connection_string)

mongo_client = get_mongo_client()
users_collection = mongo_client.Assignment.alter


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    file_ext = file.filename.split('.')[-1].lower()
    source = request.form.get('source', 'unknown')  
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  
    
    if file_ext not in ['csv', 'json']:
        return jsonify({"error": "Unsupported file format"}), 400

    try:
        temp_file_path = os.path.join(TEMP_DIR, file.filename)
        file.save(temp_file_path)  

        if file_ext == 'csv':
            if os.stat(temp_file_path).st_size == 0:
                return jsonify({"error": "Uploaded CSV file is empty"}), 400
            
            df = pd.read_csv(temp_file_path)
            if df.empty:
                return jsonify({"error": "CSV file has no data"}), 400
            
            count = df.shape[0]

        else:  
            file.seek(0)  
            with open(temp_file_path, 'r') as f:
                data = json.load(f)

            if isinstance(data, dict) and "data" in data:
                flat_data = flatten_json(data["data"])
                df = pd.DataFrame([flat_data])  
                count = df.shape[0]
            else:
                return jsonify({"error": "Invalid JSON format. Expected a 'data' key with an object"}), 400

        is_valid, message = validate_data(df)
        if not is_valid:
            os.remove(temp_file_path)  
            return jsonify({"error": message}), 400

        new_filename = f"{source}_{timestamp}.{file_ext}"
        new_file_path = os.path.join(TEMP_DIR, new_filename)
        os.rename(temp_file_path, new_file_path)
        
        gcp_response = upload_to_gcp(new_file_path, new_filename)

        return jsonify({"message": gcp_response, "records_uploaded": count}), 200

    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return jsonify({"error": str(e)}), 500
        


@app.route('/user', methods=['GET'])
def user_lookup():
    email = request.args.get('email')
    cookie = request.args.get('cookie')

    if not email and not cookie:
        return jsonify({"error": "Please provide an email or cookie"}), 400

    query = {}
    if email: query["email"] = email
    if cookie: query["cookie"] = cookie

    user_data = users_collection.find_one(query, {"_id": 0, 'embeddings': 0})
    if not user_data:
        return jsonify({"error": "User not found"}), 404

    location_keys = {'city', 'state', 'country'}
    demographics_keys = {'education', 'gender', 'income', 'age'}

    user_info = {
        k: v for k, v in user_data.items()
        if k not in location_keys and k not in demographics_keys
    }
    user_info['location'] = {k: user_data[k] for k in location_keys if k in user_data}
    user_info['demographics'] = {k: user_data[k] for k in demographics_keys if k in user_data}

    return jsonify({'data': user_info}), 200

@app.route("/similar_users", methods=["GET"])
def similar_users():
    email = request.args.get("email")
    cookie = request.args.get("cookie")
    cohort = request.args.get("cohort")
    limit = int(request.args.get("limit", 10))  # Default limit = 10
    offset = int(request.args.get("offset", 0)) # Default offset = 0

    if not email and not cookie:
        return jsonify({"error": "Email or cookie is required"}), 400
    if offset > 5:
        return jsonify({"error": "Offset cannot be greater than 5"}), 400

    if limit > 15:
        return jsonify({"error": "Limit cannot be greater than 15"}), 400

    query = {"email": email} if email else {"cookie": cookie}
    user_data = users_collection.find_one(query, {"_id": 0, "embeddings": 1})

    if not user_data or "embeddings" not in user_data:
        return jsonify({"error": "User not found or missing embeddings"}), 404

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embeddings",
                "queryVector": user_data["embeddings"],
                "numCandidates": 150,
                "limit": 100
            }
        },
        {
            "$project": {
                "_id": 0,
                "email": 1,
                "cohort": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]

    results = list(users_collection.aggregate(pipeline))
    similar_users = [
        {k: v for k, v in user.items() if k != "cohort"}
        for user in results
        if not cohort or cohort in user.get("cohort", [])
    ]

    if similar_users:
        similar_users = similar_users[1:]  # Remove the user themselves

    return jsonify({
        "cohort": cohort,
        "data": similar_users[offset:offset + limit]
    }), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)), debug=True)

