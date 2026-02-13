import edge_tts

from extractors import TTS_PAUSE

_voices_cache = None

# Silent MPEG2 Layer III frame: 24 kHz, 64 kbps, mono — matches edge-tts output.
# Each frame is 192 bytes and plays ~24 ms of silence.
_SILENT_FRAME = bytes.fromhex("fff364c4") + b"\x00" * 188
SILENCE = _SILENT_FRAME * 63  # ~1.5 s pause between paragraphs


async def _fetch_voices():
    """Fetch available voices from Edge TTS."""
    return await edge_tts.list_voices()


def get_voices(language_prefix="en"):
    """Return a list of available English voices, cached after first call.

    Each voice is a dict with keys: name, friendly_name, gender.
    """
    global _voices_cache
    if _voices_cache is None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    _voices_cache = pool.submit(
                        asyncio.run, _fetch_voices()
                    ).result()
            else:
                _voices_cache = loop.run_until_complete(_fetch_voices())
        except RuntimeError:
            _voices_cache = asyncio.run(_fetch_voices())

    return [
        {
            "name": v["ShortName"],
            "friendly_name": v["FriendlyName"],
            "gender": v["Gender"],
        }
        for v in _voices_cache
        if v["ShortName"].startswith(language_prefix)
    ]


def convert_to_speech(text, output_path, voice, rate, progress_callback=None):
    """Convert text to speech using edge-tts and save as MP3.

    Args:
        text: The text to convert.
        output_path: Path to write the MP3 file.
        voice: Edge TTS voice name (e.g. "en-US-AriaNeural").
        rate: Speed adjustment string (e.g. "+0%", "+20%", "-10%").
        progress_callback: Optional callable(percent: float, message: str).
    """
    import asyncio

    async def _convert():
        # Split text on the pause marker.  Each resulting segment is
        # converted in its own edge-tts call, and 1.5 s of silent MP3
        # frames are written between them so the listener hears a clear
        # break at every paragraph / line break.
        segments = [s.strip() for s in text.split(TTS_PAUSE) if s.strip()]

        total_bytes = 0
        estimated_size = max(len(text) * 150, 1)

        with open(output_path, "wb") as f:
            for idx, seg_text in enumerate(segments):
                communicate = edge_tts.Communicate(seg_text, voice, rate=rate)
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                        total_bytes += len(chunk["data"])
                        if progress_callback:
                            raw_pct = min(total_bytes / estimated_size, 1.0)
                            pct = 20 + raw_pct * 75
                            progress_callback(pct, "Converting to speech...")
                # Write silence after every segment except the last.
                if idx < len(segments) - 1:
                    f.write(SILENCE)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _convert()).result()
        else:
            loop.run_until_complete(_convert())
    except RuntimeError:
        asyncio.run(_convert())

    if progress_callback:
        progress_callback(95, "Finalizing audio...")
