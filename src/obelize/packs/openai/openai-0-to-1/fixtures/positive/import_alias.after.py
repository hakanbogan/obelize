import openai as oai

oai.organization = "org-example"


def reply(prompt):
    response = oai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        n=2,
    )
    first = response.choices[0].message.content
    second = response.choices[1].message.content
    return [first, second]
