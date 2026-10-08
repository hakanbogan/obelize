import openai


def transcribe(path):
    with open(path, "rb") as audio:
        return openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            language="en",
            temperature=0.2,
        ).text


def translate(path):
    with open(path, "rb") as audio:
        transcript = openai.audio.translations.create(model="whisper-1", file=audio, prompt="notes")
    return transcript.text
