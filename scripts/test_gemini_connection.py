import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing")

client = genai.Client(api_key=api_key)

try:
    print("Checking Gemini API connection...")

    models = list(client.models.list())

    print("API authentication successful!")
    print(f"Models available: {len(models)}")

    required_models = [
        "models/gemini-3.8-flash",
        "models/gemini-3.5-flash-lite",
    ]

    available = {model.name for model in models}

    for model_name in required_models:
        status = "Available" if model_name in available else "Not listed"
        print(f"{model_name}: {status}")

except Exception as e:
    print(f"Connection failed: {type(e).__name__}: {e}")

finally:
    client.close()