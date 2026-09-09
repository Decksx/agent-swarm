import os
import time
import requests
import re
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Missing GEMINI_API_KEY environment variable.")

client = genai.Client(api_key=API_KEY)
HUB_URL = "http://localhost:8050"
LAST_SEEN_ID = 0

SYSTEM_INSTRUCTION = """You are the Lead Software Architect coordinating an engineering swarm.
Your team:
- @ClaudeCode: Runs in the actual project workspace on the dev machine. Can execute bash commands, run test suites, inspect file trees, and edit local code.
- @ChatGPT: Handles static code writing and GitHub updates.
- @Admin: The human owner.

Guidelines:
1. Break tasks down into clear, single operational steps.
2. Directly address the next responsible agent at the start of your message (e.g. '@ClaudeCode ...' or '@ChatGPT ...').
3. Keep instructions concise, technical, and actionable.
4. When a worker posts test output or command results, inspect them and dictate the next step."""

def poll_and_orchestrate():
    global LAST_SEEN_ID
    try:
        resp = requests.get(f"{HUB_URL}/messages?since_id={LAST_SEEN_ID}", timeout=5).json()
    except Exception as e:
        print(f"Error reading hub: {e}")
        return

    for msg in resp:
        LAST_SEEN_ID = max(LAST_SEEN_ID, msg["id"])
        
        # Don't respond to own messages
        if msg["sender"] == "Gemini":
            continue

        # Trigger if addressed directly or if human Admin posts a new goal
        if msg["target"].lower() in ["@gemini", "gemini", "lead"] or (msg["sender"] == "Admin" and msg["target"] == "All"):
            print(f"\n[LEAD ACTIVATED by {msg['sender']}]: {msg['content']}")
            
            prompt = f"Sender: {msg['sender']}\nMessage: {msg['content']}"
            
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config={"system_instruction": SYSTEM_INSTRUCTION}
            )
            
            reply_text = response.text
            
            # Determine target agent based on mention
            target = "@ClaudeCode"
            if "@chatgpt" in reply_text.lower():
                target = "@ChatGPT"
            elif "@admin" in reply_text.lower():
                target = "@Admin"

            requests.post(f"{HUB_URL}/send", json={
                "sender": "Gemini",
                "target": target,
                "content": reply_text
            })
            print(f"[DIRECTIVE POSTED to {target}]")

if __name__ == "__main__":
    print("Gemini Lead Orchestrator running. Polling hub...")
    while True:
        poll_and_orchestrate()
        time.sleep(3)
