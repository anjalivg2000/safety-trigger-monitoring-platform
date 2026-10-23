import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("ERROR: OPENAI_API_KEY was not found.")
    exit()

print("API key found.")

try:
    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model="gpt-5.5",
        input="Reply with exactly: OpenAI connection successful."
    )

    print("SUCCESS!")
    print(response.output_text)

except Exception as e:
    print("OpenAI connection failed.")
    print(type(e).__name__)
    print(e)