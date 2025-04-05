import pandas as pd

def validate_data(df):
    """Validation: Ensure 'cookie' and 'email' exist in all records"""
    required_columns = {"cookie", "email"}
    missing_cols = required_columns - set(df.columns)
    
    if missing_cols:
        return False, f"Missing required columns: {missing_cols}. Found: {list(df.columns)}"
    
    if df[['cookie', 'email']].isnull().all(axis=1).any():
        return False, "Error: 'cookie' and 'email' both are missing in some records."
    
    return True, "Valid data"

def flatten_json(nested_json):
    """Flatten nested JSON structures"""
    flat_data = {}
    for key, value in nested_json.items():
        if isinstance(value, dict):  
            for sub_key, sub_value in value.items():  
                flat_data[sub_key] = sub_value  
        elif isinstance(value, list):
            flat_data[key] = ", ".join(map(str, value))
        else:
            flat_data[key] = value
    return flat_data
