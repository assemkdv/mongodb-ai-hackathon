"""Text-to-speech: stream a line of dialogue through ElevenLabs.

The audio is forwarded to the browser chunk by chunk as ElevenLabs produces
it, so playback starts before the whole clip exists.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.agent.delivery import first_reply, parse_delivery, shape_for_speech, voice_settings
from app.http import get_http
from app.schemas import TtsRequest

router = APIRouter()

# 32kbps keeps the first byte fast. It's a voice through laptop speakers.
OUTPUT_FORMAT = "mp3_22050_32"


@router.post("/api/tts")
async def tts(body: TtsRequest):
    delivery, line = parse_delivery(first_reply(body.text))
    if not line:
        raise HTTPException(400, "`text` contained a delivery tag but no line")

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # "Sarah"
    payload = {
        "text": shape_for_speech(line),
        "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"),
        "voice_settings": voice_settings(delivery),
    }
    if body.previousText:
        payload["previous_text"] = body.previousText[-500:]

    http = get_http()
    upstream = await http.send(
        http.build_request(
            "POST",
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
            params={"output_format": OUTPUT_FORMAT},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Accept": "audio/mpeg"},
            json=payload,
        ),
        stream=True,
    )

    if upstream.status_code != 200:
        detail = (await upstream.aread()).decode(errors="replace")[:500]
        await upstream.aclose()
        # Bad key (401) and out of credits (429) are worth passing through as-is.
        status = upstream.status_code if upstream.status_code in (401, 429) else 502
        raise HTTPException(status, f"ElevenLabs {upstream.status_code}: {detail}")

    return StreamingResponse(
        upstream.aiter_raw(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            # Lets the browser show the delivery it's about to hear.
            "X-Delivery": f"{delivery['pace']}|{delivery['energy']}|{delivery['manner']}",
        },
        background=BackgroundTask(upstream.aclose),
    )
