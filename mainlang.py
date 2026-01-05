from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import httpx
import os

app = FastAPI()

# =========================
# CONFIG
# =========================
BASE_URL = os.getenv("BASE_URL")   # set AFTER deployment
CHAT_ENDPOINT = "https://iomp-backend.onrender.com/chat"
LANGUAGE = "en-IN"


def twiml(vr: VoiceResponse):
    return Response(str(vr), media_type="text/xml")


# =========================
# CALL START – WELCOME
# =========================
@app.post("/voice")
async def voice():
    vr = VoiceResponse()

    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process",
        method="POST",
        language=LANGUAGE,
        speech_timeout="auto",
    )

    gather.say(
        "Welcome to LIC customer support. "
        "I am here to help you with your LIC related questions. "
        "Please ask your question after the beep."
    )

    vr.append(gather)

    # Fallback if caller stays silent
    vr.say(
        "I did not hear any question. "
        "Thank you for calling LIC. Goodbye."
    )
    vr.hangup()

    return twiml(vr)


# =========================
# PROCESS USER QUESTION
# =========================
@app.post("/process")
async def process(request: Request):
    form = await request.form()
    speech = form.get("SpeechResult")

    vr = VoiceResponse()

    # If no speech detected
    if not speech:
        vr.say(
            "Sorry, I could not hear you clearly. "
            "Please call again if you need any help. Goodbye."
        )
        vr.hangup()
        return twiml(vr)

    # Get answer from chat backend
    answer = await ask_chat(speech)

    # Speak the answer
    vr.say(answer)

    # Ask follow-up question
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process",
        method="POST",
        language=LANGUAGE,
        speech_timeout="auto",
    )

    gather.say(
        "Would you like to ask another question? "
        "You can speak now."
    )

    vr.append(gather)

    # Final fallback if user stays silent again
    vr.say(
        "Thank you for calling LIC customer support. "
        "Have a great day. Goodbye."
    )
    vr.hangup()

    return twiml(vr)


# =========================
# CHAT BACKEND CALL
# =========================
async def ask_chat(question: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                CHAT_ENDPOINT,
                json={"question": question}
            )

            if response.status_code != 200:
                return (
                    "Sorry, I am unable to get the information right now. "
                    "Please try again later."
                )

            data = response.json()
            return data.get(
                "answer",
                "Sorry, I could not find the information for that question."
            )

    except Exception:
        return (
            "Sorry, something went wrong while answering your question. "
            "Please try again later."
        )


# =========================
# HEALTH CHECK
# =========================
@app.get("/health")
async def health():
    return {"status": "ok"}
