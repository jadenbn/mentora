from google import genai
from google.genai import types
import time
import os
import multiprocessing

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


start = time.perf_counter()

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="what is x if 5x+3=12. answer with one word",
    config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL"  # Options: "MINIMAL", "LOW", "MEDIUM", "HIGH"
        )
    ),
)
end = time.perf_counter()

print(response.text)
print(f"time: {end - start}")

