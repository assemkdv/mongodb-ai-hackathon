"""Streams Claude's words into ElevenLabs and the audio out to the browser,
all at the same time.

Without streaming:   [Claude writes the whole line] -> [ElevenLabs speaks it]
With streaming:      Claude:     [tag][words....................]
                     ElevenLabs:      [audio..........................]
                     Browser:          [plays.........................]

Audio starts as soon as Claude has written the delivery tag and the first
phrase, instead of after the whole reply. That's where the latency goes down.
"""

import asyncio
import base64
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable

from websockets.asyncio.client import connect

from app.agent.delivery import TAG, parse_delivery, voice_settings

# Text goes to ElevenLabs one phrase at a time (up to the last punctuation
# mark), so it starts speaking right away instead of waiting for a buffer.
PHRASE_END = re.compile(r"[.!?,;:—…]")
# A second delivery tag means Claude started another line: stop there.
SECOND_TAG = re.compile(r"\n\s*\[[a-z]+\s*\|", re.IGNORECASE)


def elevenlabs_url() -> str:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
    return (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id={model_id}&output_format=mp3_22050_32"
    )


async def speak_streaming(
    words: AsyncIterator[str],
    send_audio: Callable[[bytes], Awaitable[None]],
    on_reply: Callable[[str], Awaitable[None]],
) -> str:
    """words: Claude's reply, piece by piece.
    send_audio: called with each MP3 chunk as ElevenLabs produces it.
    on_reply: called with the full reply text as soon as Claude finishes.
    Returns the full reply (delivery tag included)."""

    # Open the ElevenLabs connection now, while Claude is still thinking,
    # so the ~150ms handshake is already done when the first words arrive.
    elevenlabs = await connect(
        elevenlabs_url(), additional_headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
    )
    forward_audio = asyncio.create_task(_forward_audio(elevenlabs, send_audio))

    try:
        reply = ""  # everything Claude has written
        sent_upto = 0  # how much of `reply` ElevenLabs already has
        started = False  # voice settings sent yet?

        async for piece in words:
            reply += piece

            if not started:
                # Wait for the [pace|energy|manner] tag: the voice settings
                # depend on it, and they have to be sent first.
                match = TAG.match(reply)
                if not match and (len(reply) < 40 or reply.lstrip().startswith("[")):
                    continue
                delivery, _ = parse_delivery(reply)
                await elevenlabs.send(json.dumps({"text": " ", "voice_settings": voice_settings(delivery)}))
                sent_upto = match.end() if match else 0
                started = True

            if SECOND_TAG.search(reply):
                reply = reply[: SECOND_TAG.search(reply).start()]
                break

            pending = reply[sent_upto:]
            ends = [m.end() for m in PHRASE_END.finditer(pending)]
            if ends and pending[: ends[-1]].strip():
                # Everything up to the last punctuation mark is a complete
                # phrase. "flush" tells ElevenLabs to voice it right now.
                phrase = pending[: ends[-1]]
                await elevenlabs.send(json.dumps({"text": _speakable(phrase), "flush": True}))
                sent_upto += len(phrase)

        if not started:  # very short reply, never got past the tag check
            delivery, _ = parse_delivery(reply)
            await elevenlabs.send(json.dumps({"text": " ", "voice_settings": voice_settings(delivery)}))
            sent_upto = TAG.match(reply).end() if TAG.match(reply) else 0

        await on_reply(reply.strip())

        if reply[sent_upto:].strip():
            await elevenlabs.send(json.dumps({"text": _speakable(reply[sent_upto:]), "flush": True}))
        await elevenlabs.send(json.dumps({"text": ""}))  # end of input

        await forward_audio  # wait until the last audio chunk is delivered
        return reply.strip()
    finally:
        forward_audio.cancel()
        await elevenlabs.close()


async def _forward_audio(elevenlabs, send_audio) -> None:
    """ElevenLabs sends JSON messages with base64 audio; pass the raw MP3 on."""
    async for message in elevenlabs:
        data = json.loads(message)
        if data.get("audio"):
            await send_audio(base64.b64decode(data["audio"]))
        if data.get("isFinal"):
            return


def _speakable(text: str) -> str:
    """ElevenLabs needs a space after an em dash to pause on it."""
    text = re.sub(r"\s*—\s*", "— ", text)
    return text if text.endswith(" ") else text + " "
