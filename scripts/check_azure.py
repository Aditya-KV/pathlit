"""Phase 0: call each Azure service once. Prints PASS/FAIL/SKIP and timing. Sends only text (and one tiny generated image for Vision)."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pathlit.config import env  # noqa: E402


def timed(name: str, needs: list[str], fn) -> None:
    missing = [k for k in needs if not env(k)]
    if missing:
        print(f"SKIP  {name}: missing {', '.join(missing)} in .env")
        return
    t0 = time.perf_counter()
    try:
        detail = fn()
        print(f"PASS  {name}: {round((time.perf_counter() - t0) * 1000)} ms  {detail or ''}")
    except Exception as e:
        print(f"FAIL  {name}: {type(e).__name__}: {str(e)[:300]}")


def openai_small() -> str:
    from openai import AzureOpenAI
    c = AzureOpenAI(azure_endpoint=env("AZURE_OPENAI_ENDPOINT"), api_key=env("AZURE_OPENAI_API_KEY"),
                    api_version=env("AZURE_OPENAI_API_VERSION"), timeout=10)
    r = c.chat.completions.create(model=env("AZURE_OPENAI_DEPLOYMENT_SMALL"), temperature=0.2,
                                  messages=[{"role": "user", "content": "Reply with the single word: ok"}])
    return f"reply={r.choices[0].message.content!r} tokens={r.usage.total_tokens}"


def speech() -> str:
    import azure.cognitiveservices.speech as sp
    cfg = sp.SpeechConfig(subscription=env("AZURE_SPEECH_KEY"), region=env("AZURE_SPEECH_REGION"))
    # synthesize to memory only (no speaker) so the check is silent and measures time to audio
    synth = sp.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    r = synth.speak_text_async("Let's start with the donut shape.").get()
    if r.reason != sp.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError(str(r.reason))
    return f"audio_bytes={len(r.audio_data)}"


def vision() -> str:
    from azure.ai.vision.imageanalysis import ImageAnalysisClient
    from azure.ai.vision.imageanalysis.models import VisualFeatures
    from azure.core.credentials import AzureKeyCredential
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 100), "white")
    ImageDraw.Draw(img).text((20, 40), "Add Mesh", fill="black")
    buf = io.BytesIO(); img.save(buf, "PNG")
    c = ImageAnalysisClient(env("AZURE_VISION_ENDPOINT"), AzureKeyCredential(env("AZURE_VISION_KEY")))
    r = c.analyze(image_data=buf.getvalue(), visual_features=[VisualFeatures.READ])
    lines = [l.text for b in (r.read.blocks if r.read else []) for l in b.lines]
    return f"lines={lines}"


def search() -> str:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient
    c = SearchIndexClient(env("AZURE_SEARCH_ENDPOINT"), AzureKeyCredential(env("AZURE_SEARCH_KEY")))
    return f"indexes={[i for i in c.list_index_names()]}"


timed("Azure OpenAI (small)", ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_DEPLOYMENT_SMALL"], openai_small)
timed("Azure Speech (TTS)", ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"], speech)
timed("Azure Vision (OCR)", ["AZURE_VISION_ENDPOINT", "AZURE_VISION_KEY"], vision)
timed("Azure AI Search", ["AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY"], search)
