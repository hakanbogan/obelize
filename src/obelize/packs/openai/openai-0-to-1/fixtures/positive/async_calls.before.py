import openai


async def reply(prompt):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


async def picture(prompt):
    return await openai.Image.acreate(prompt=prompt)


async def heard(audio):
    return await openai.Audio.atranscribe("whisper-1", audio)
