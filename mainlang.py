"""Twilio voice bridge for LIC assistant.

This app handles outbound Twilio calls, plays a greeting, captures speech,
sends the transcript to the /chat endpoint, converts the reply via /tts,
and streams the audio back to the caller. Keep PUBLIC_BASE_URL reachable by
Twilio (e.g., via Render deployment or an ngrok tunnel).
"""

import os
import logging
from typing import Dict, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Gather, VoiceResponse

load_dotenv()

logger = logging.getLogger("twilio_voice")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# Remote endpoints (point to deployed backend)
CHAT_ENDPOINT = os.getenv("CHAT_ENDPOINT", "https://iomp-backend.onrender.com/chat")

# Public base URL where this FastAPI app is reachable by Twilio.
# Prefer env so the tunnel/domain can rotate without code changes.
PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL", "https://twiolio-customer-support.onrender.com"
)
if not PUBLIC_BASE_URL:
    logger.warning("PUBLIC_BASE_URL is not set; Twilio callbacks will fail.")

WELCOME_PROMPT = os.getenv(
    "WELCOME_PROMPT",
    "Welcome to LIC. With you, every moment of your life. "
    "Hope you are satisfied with your current policy. "
    "You can ask your question now."
)
FOLLOWUP_PROMPT = os.getenv(
    "FOLLOWUP_PROMPT",
    "Do you have another question?"
)
SPEECH_LANGUAGE = os.getenv("SPEECH_LANGUAGE", "en-IN")
SPEECH_TIMEOUT = os.getenv("SPEECH_TIMEOUT", "auto")  # auto or seconds as string

# Max consecutive silences before auto-hangup
MAX_SILENCE_COUNT = 2

app = FastAPI()

# Track silence count per call (keyed by CallSid)
silence_tracker: Dict[str, int] = {}


def _abs(path: str) -> str:
    """Build absolute URL for Twilio callbacks."""
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL env var is required for Twilio.")
    return f"{PUBLIC_BASE_URL.rstrip('/')}{path}"


def _twiml_response(vr: VoiceResponse) -> Response:
    """Convert VoiceResponse to XML HTTP response."""
    return Response(content=str(vr), media_type="text/xml")


@app.api_route("/voice/answer", methods=["GET", "POST"])
async def voice_answer(request: Request) -> Response:
    """Initial TwiML: greet and gather speech with barge-in support."""
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    # Reset silence counter for new call
    silence_tracker[call_sid] = 0

    vr = VoiceResponse()
    # Gather wraps Say so user can interrupt (barge-in)
    gather = Gather(
        input="speech",
        action=_abs("/voice/process"),
        method="POST",
        speech_timeout=SPEECH_TIMEOUT,
        language=SPEECH_LANGUAGE,
        barge_in=True,  # Allow user to interrupt
    )
    gather.say(WELCOME_PROMPT)
    vr.append(gather)
    # If no speech detected, redirect to timeout handler
    vr.redirect(_abs("/voice/timeout"), method="POST")
    return _twiml_response(vr)


@app.api_route("/voice/process", methods=["GET", "POST"])
async def voice_process(request: Request) -> Response:
    """Handle speech result, call /chat, and speak the reply using Twilio's voice."""
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    transcript: Optional[str] = form.get("SpeechResult")

    if not transcript:
        # No speech detected - redirect to timeout handler
        vr = VoiceResponse()
        vr.redirect(_abs("/voice/timeout"), method="POST")
        return _twiml_response(vr)

    # Reset silence counter since user spoke
    silence_tracker[call_sid] = 0
    logger.info("Received speech: %s", transcript)

    try:
        answer_text, should_end = await _ask_chat(transcript)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Voice processing failed: %s", exc)
        vr = VoiceResponse()
        vr.say("Sorry, something went wrong while answering your question.")
        vr.redirect(_abs("/voice/timeout"), method="POST")
        return _twiml_response(vr)

    # Check if LLM indicated user wants to end the call
    if should_end:
        logger.info("LLM indicated end of conversation")
        vr = VoiceResponse()
        vr.say("Thank you for calling LIC. Have a great day. Goodbye.")
        vr.hangup()
        silence_tracker.pop(call_sid, None)
        return _twiml_response(vr)

    vr = VoiceResponse()
    # Wrap the answer in Gather so user can interrupt (barge-in)
    gather = Gather(
        input="speech",
        action=_abs("/voice/process"),
        method="POST",
        speech_timeout=SPEECH_TIMEOUT,
        language=SPEECH_LANGUAGE,
        barge_in=True,  # Allow user to interrupt while agent speaks
    )
    # Speak the answer - user can interrupt at any time
    gather.say(answer_text)
    gather.say(FOLLOWUP_PROMPT)
    vr.append(gather)
    # If no speech after gather, go to timeout handler
    vr.redirect(_abs("/voice/timeout"), method="POST")
    return _twiml_response(vr)


@app.api_route("/voice/timeout", methods=["GET", "POST"])
async def voice_timeout(request: Request) -> Response:
    """Handle silence/timeout - end call after max retries."""
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")

    # Increment silence counter
    count = silence_tracker.get(call_sid, 0) + 1
    silence_tracker[call_sid] = count
    logger.info("Silence timeout #%d for call %s", count, call_sid)

    vr = VoiceResponse()
    if count >= MAX_SILENCE_COUNT:
        # End the call after max silences
        vr.say("I haven't heard from you. Thank you for calling. Goodbye.")
        vr.hangup()
        silence_tracker.pop(call_sid, None)
    else:
        # Give another chance
        gather = Gather(
            input="speech",
            action=_abs("/voice/process"),
            method="POST",
            speech_timeout=SPEECH_TIMEOUT,
            language=SPEECH_LANGUAGE,
            barge_in=True,
        )
        gather.say("I didn't catch that. Do you have any questions?")
        vr.append(gather)
        vr.redirect(_abs("/voice/timeout"), method="POST")
    return _twiml_response(vr)


@app.get("/health")
async def health() -> Dict[str, str]:
    """Lightweight health endpoint for external reachability checks."""
    return {"status": "ok"}


async def _ask_chat(question: str) -> tuple[str, bool]:
    """Ask chat endpoint and return (answer, should_end_call)."""
    payload = {"question": question}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(CHAT_ENDPOINT, json=payload)
        resp.raise_for_status()
        data = resp.json()
    answer = data.get("answer") or "Sorry, I can't find that right now."
    logger.info("Chat answer: %s", answer)

    # Check if LLM returned end_call signal
    should_end = False
    if 'end_call' in answer.lower() and 'true' in answer.lower():
        should_end = True
        # Don't speak the JSON response, say goodbye instead
        answer = ""
    
    return answer, should_end


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run("mainlang:app", host="0.0.0.0", port=port)
