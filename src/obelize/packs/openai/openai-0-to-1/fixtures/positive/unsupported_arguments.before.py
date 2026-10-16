import openai


def streamed(prompt):
    for chunk in openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], stream=True
    ):
        print(chunk.choices[0].delta)


def azure(prompt):
    openai.ChatCompletion.create(
        deployment_id="my-deployment", messages=[{"role": "user", "content": prompt}]
    )


def two_names(prompt):
    openai.ChatCompletion.create(
        engine="a", model="b", messages=[{"role": "user", "content": prompt}]
    )


def no_deadline(prompt):
    openai.ChatCompletion.create(model="gpt-4o-mini", messages=[], request_timeout=(3, 30))


def per_call_key(prompt, key):
    openai.ChatCompletion.create(model="gpt-4o-mini", messages=[], api_key=key)


def positional(prompt):
    openai.Embedding.create(prompt, "text-embedding-3-small")


def splat(options):
    openai.Completion.create(**options)
