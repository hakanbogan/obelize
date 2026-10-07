import openai


async def reply(prompt):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
