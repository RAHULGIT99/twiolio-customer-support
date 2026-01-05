

import os
import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

app = FastAPI()

# --- CONFIGURATION ---
# TODO: Add your Groq API Key here or in .env
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")
LIC_BACKEND_URL = "https://iomp-backend.onrender.com/chat"

# --- HELPER 1: INTENT ANALYSIS (GROQ) ---
async def analyze_intent(user_text: str) -> str:
    """
    Uses Groq to classify if the user wants to END the conversation or ASK a question.
    Returns: 'CALL_END' or 'CALL_CONTINUE'
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Strict System Prompt for Classification
    system_prompt = (
        "You are a call routing assistant. Your ONLY job is to classify the user's intent. "
        "If the user says 'no', 'no thanks', 'bye', 'goodbye', 'nothing', 'that is all', or indicates they are done, output 'CALL_END'. "
        "If the user asks a question, says 'yes', or wants information, output 'CALL_CONTINUE'. "
        "Output ONLY one of these two strings. Do not add punctuation."
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.0  # Set to 0 for strict classification
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"].strip()
                print(f"Groq Intent Analysis: {result}") # Debug log
                return result
            else:
                print(f"Groq Error: {response.status_code}")
                return "CALL_CONTINUE" # Default to continue if AI fails
    except Exception as e:
        print(f"Groq Exception: {e}")
        return "CALL_CONTINUE"

# --- HELPER 2: GET ANSWER (YOUR BACKEND) ---
async def ask_lic_backend(question: str) -> str:
    print(f"Sending to LIC Backend: {question}") 
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                LIC_BACKEND_URL,
                json={"question": question}
            )
            if response.status_code != 200:
                return "I am having trouble accessing the database right now."
            data = response.json()
            return data.get("answer", "I didn't find an answer for that.")
    except Exception:
        return "Sorry, I am unable to connect to the server."

# --- TWILIO ROUTES ---

@app.get("/")
async def index():
    return {"message": "Smart Intent Bot Running"}

@app.post("/voice/answer")
async def voice_answer():
    resp = VoiceResponse()
    resp.pause(length=1)
    
    # Initial Welcome with Barge-In
    gather = Gather(input='speech', action='/voice/handle-input', timeout=60, speechTimeout='auto')
    gather.say("Welcome to LIC customer support. How can I help you today?")
    resp.append(gather)
    
    resp.redirect("/voice/wait-step-2")
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/handle-input")
async def handle_input(request: Request, SpeechResult: str = Form(None)):
    resp = VoiceResponse()
    
    # 1. Handle Silence
    if not SpeechResult:
        resp.redirect("/voice/wait-step-2")
        return Response(content=str(resp), media_type="application/xml")

    print(f"User said: {SpeechResult}")

    # 2. CALL GROQ TO ANALYZE INTENT
    intent = await analyze_intent(SpeechResult)

    # 3. DECISION LOGIC
    if intent == "CALL_END":
        resp.say("Thank you for calling LIC. Have a wonderful day. Goodbye.")
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")

    # 4. IF CONTINUE: Get real answer from your backend
    ai_answer = await ask_lic_backend(SpeechResult)

    # 5. Speak Answer (With Barge-In enabled)
    gather = Gather(
        input='speech', 
        action='/voice/handle-input', 
        timeout=60, 
        speechTimeout='auto'
    )
    
    # Speak the answer
    gather.say(ai_answer)
    
    # Prompt for next turn
    gather.pause(length=1)
    gather.say("Do you have any other questions?")
    
    resp.append(gather)
    
    # Fallback to wait loop
    resp.redirect("/voice/wait-step-2")

    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/wait-step-2")
async def wait_step_2():
    """Wait loop: Adds another 60s listening time."""
    resp = VoiceResponse()
    gather = Gather(input='speech', action='/voice/handle-input', timeout=60, speechTimeout='auto')
    resp.append(gather)
    
    # If 120s total passed:
    resp.say("I am disconnecting due to inactivity. Goodbye.")
    resp.hangup()
    return Response(content=str(resp), media_type="application/xml")