import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.8-flash")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from .env")

client = genai.Client(api_key=api_key)

print(f"Testing Gemini generation with model: {model}")

try:
    response = client.models.generate_content(
        model=model,
        contents="Reply with exactly: Gemini API generation successful."
    )

    print("\nResponse:")
    print(response.text)

except Exception as exc:
    print(f"\nGemini generation failed: {type(exc).__name__}: {exc}")