import openai


def streamed(prompt):
    for chunk in openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], stream=True
    ):
        print(chunk.choices[0].delta)


def azure(prompt):
    openai.ChatCompletion.create(engine="my-deployment", messages=[{"role": "user", "content": prompt}])


def per_call_key(prompt, key):
    openai.ChatCompletion.create(model="gpt-4o-mini", messages=[], api_key=key)


def positional(prompt):
    openai.Embedding.create(prompt, "text-embedding-3-small")


def splat(options):
    openai.Completion.create(**options)
