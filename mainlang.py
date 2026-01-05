from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

app = FastAPI()

@app.get("/")
async def index():
    return {"message": "LIC Voice Bot Running"}

@app.post("/voice/answer")
async def voice_answer():
    resp = VoiceResponse()
    resp.say("Welcome to LIC customer support. I am here to help you with your LIC related questions.")
    resp.redirect("/voice/listen")
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/listen")
async def voice_listen():
    resp = VoiceResponse()
    gather = Gather(input='speech', action='/voice/handle-question', timeout=3)
    gather.say("Please ask your question.")
    resp.append(gather)
    resp.redirect("/voice/listen")
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/handle-question")
async def handle_question(request: Request, SpeechResult: str = Form(...)):
    resp = VoiceResponse()
    
    # Logic to process SpeechResult goes here
    print(f"User said: {SpeechResult}")
    resp.say(f"I heard you say: {SpeechResult}. Here is the answer.")

    gather = Gather(input='speech', action='/voice/decision', timeout=3)
    gather.say("Would you like to ask another question?")
    resp.append(gather)
    
    resp.redirect("/voice/decision")
    return Response(content=str(resp), media_type="application/xml")

@app.post("/voice/decision")
async def decision(request: Request, SpeechResult: str = Form(None)):
    resp = VoiceResponse()
    user_input = SpeechResult.lower() if SpeechResult else ""

    if "yes" in user_input or "yeah" in user_input:
        resp.say("Okay.")
        resp.redirect("/voice/listen")
    else:
        resp.say("Thank you for calling LIC customer support. Have a great day. Goodbye.")
        resp.hangup()

    return Response(content=str(resp), media_type="application/xml")