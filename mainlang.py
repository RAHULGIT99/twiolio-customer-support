import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

app = FastAPI()

# --- CONFIG ---
CHAT_ENDPOINT = "https://iomp-backend.onrender.com/chat"

async def ask_chat(question: str) -> str:
    print(f"Sending to backend: {question}") 
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                CHAT_ENDPOINT,
                json={"question": question}
            )
            if response.status_code != 200:
                return "Sorry, I am unable to connect to the server right now."
            data = response.json()
            return data.get("answer", "Sorry, I received an empty answer.")
    except Exception as e:
        print(f"Exception: {e}")
        return "Sorry, there was a technical error."

# --- ROUTES ---

@app.get("/")
async def index():
    return {"message": "LIC Voice Bot Running"}

@app.post("/voice/answer")
async def voice_answer():
    resp = VoiceResponse()
    resp.pause(length=1)
    
    # Enable Barge-in for the welcome message too
    gather = Gather(input='speech', action='/voice/handle-input', timeout=60, speechTimeout='auto')
    gather.say("Welcome to LIC customer support. I am here to help you. You can ask me anything, or interrupt me if I talk too much.")
    resp.append(gather)
    
    # If they stay silent for 60s, go to the extension loop
    resp.redirect("/voice/wait-step-2")
    
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/handle-input")
async def handle_input(request: Request, SpeechResult: str = Form(None)):
    resp = VoiceResponse()
    
    # 1. Handle Silence (If they just made noise but said nothing)
    if not SpeechResult:
        resp.redirect("/voice/wait-step-2")
        return Response(content=str(resp), media_type="application/xml")

    user_input = SpeechResult.lower().strip()
    print(f"User said: {user_input}") 

    # 2. Smart Exit
    exit_phrases = ["no", "no thanks", "nothing", "thank you", "bye", "stop", "exit", "cancel"]
    if user_input in exit_phrases or user_input.startswith("no thanks"):
        resp.say("Thank you for calling LIC. Goodbye.")
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")

    # 3. Get Answer from Backend
    ai_answer = await ask_chat(SpeechResult)
    
    # 4. OUTPUT THE ANSWER WITH BARGE-IN ENABLED
    # We put the .say() INSIDE the Gather().
    # This means if the user speaks while the bot is answering, the bot stops and the new input is captured.
    gather = Gather(
        input='speech', 
        action='/voice/handle-input', 
        timeout=60,  # Wait 60s after the bot finishes speaking
        speechTimeout='auto'
    )
    
    # The bot speaks the answer. If user says "Stop, tell me about X", 
    # Twilio cuts this off and sends "Stop, tell me about X" to /voice/handle-input
    gather.say(ai_answer)
    
    # Add a small prompt at the end if the answer finishes completely
    gather.pause(length=1)
    gather.say("You can ask another question, or just stay silent.")
    
    resp.append(gather)

    # 5. If 60 seconds pass with silence, go to Step 2 (Wait more)
    resp.redirect("/voice/wait-step-2")

    return Response(content=str(resp), media_type="application/xml")

# --- THE 2-MINUTE WAIT LOGIC ---

@app.post("/voice/wait-step-2")
async def wait_step_2():
    """
    This is reached if the user was silent for the first 60 seconds.
    We give them ANOTHER 60 seconds.
    """
    resp = VoiceResponse()
    
    # Just listen. Don't say anything (unless you want a prompt).
    gather = Gather(input='speech', action='/voice/handle-input', timeout=60, speechTimeout='auto')
    resp.append(gather)
    
    # If we fall through here, it means 60s + 60s = 120s have passed.
    # Now we hang up.
    resp.say("I have not heard a response for a while. Disconnecting. Goodbye.")
    resp.hangup()
    
    return Response(content=str(resp), media_type="application/xml")