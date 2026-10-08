import openai


def transcribe(path):
    with open(path, "rb") as audio:
        return openai.Audio.transcribe("whisper-1", audio, language="en", temperature=0.2)["text"]


def translate(path):
    with open(path, "rb") as audio:
        transcript = openai.Audio.translate(model="whisper-1", file=audio, prompt="notes")
    return transcript.text
