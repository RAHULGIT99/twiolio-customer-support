import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

app = FastAPI()

# --- YOUR EXTERNAL BACKEND CONFIG ---
CHAT_ENDPOINT = "https://iomp-backend.onrender.com/chat"

async def ask_chat(question: str) -> str:
    """Sends the user's audio text to your backend and gets the answer."""
    print(f"Sending to backend: {question}") # Debug log
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                CHAT_ENDPOINT,
                json={"question": question}
            )

            if response.status_code != 200:
                print(f"Backend Error: {response.status_code}")
                return "Sorry, I am unable to connect to the server right now."

            data = response.json()
            # We look for the key 'answer' in your JSON response
            return data.get("answer", "Sorry, I received an empty answer.")

    except Exception as e:
        print(f"Exception calling backend: {e}")
        return "Sorry, there was a technical error getting your answer."

# --- TWILIO ROUTES ---

@app.get("/")
async def index():
    return {"message": "LIC Voice Bot Connected"}

@app.post("/voice/answer")
async def voice_answer():
    resp = VoiceResponse()
    resp.pause(length=1)
    resp.say("Welcome to LIC customer support. I am here to help you. Please ask your question.")
    resp.redirect("/voice/listen")
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/listen")
async def voice_listen():
    resp = VoiceResponse()
    
    # Listen for speech
    gather = Gather(
        input='speech', 
        action='/voice/handle-input', 
        timeout=5, 
        speechTimeout='auto'
    )
    resp.append(gather)
    
    # If silence
    resp.say("I didn't hear anything. Please ask your question.")
    resp.redirect("/voice/listen")
    
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/handle-input")
async def handle_input(request: Request, SpeechResult: str = Form(None)):
    resp = VoiceResponse()
    
    # 1. Handle Silence / No Input
    if not SpeechResult:
        resp.redirect("/voice/listen")
        return Response(content=str(resp), media_type="application/xml")

    # 2. Check for Exit Phrases (Basic NLP)
    user_input = SpeechResult.lower().strip()
    print(f"User said: {user_input}") 

    exit_phrases = ["no", "no thanks", "nothing", "thank you", "bye", "stop", "exit"]
    
    # If the user says exactly "no" or starts with "no thanks", etc.
    if user_input in exit_phrases or user_input.startswith("no thanks"):
        resp.say("Thank you for calling LIC customer support. Have a great day. Goodbye.")
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")

    # 3. Process the Question (The part I missed previously)
    # We call your function here
    ai_answer = await ask_chat(SpeechResult)
    
    # Speak the real answer from your backend
    resp.say(ai_answer)

    # 4. Loop back to ask if they have another question
    gather = Gather(
        input='speech', 
        action='/voice/handle-input', 
        timeout=4, 
        speechTimeout='auto'
    )
    gather.say("Do you have another question?")
    resp.append(gather)
    
    # If they stay silent after getting an answer, assume they are done
    resp.say("Thank you for calling. Goodbye.")
    resp.hangup()

    return Response(content=str(resp), media_type="application/xml")


@app.get("/health")
async def health():
    return {"status": "ok"}
