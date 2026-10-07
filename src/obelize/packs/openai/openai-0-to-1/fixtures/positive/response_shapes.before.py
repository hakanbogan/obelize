import openai


def dict_style(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response["choices"][0]["message"]["content"]


def passed_on(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response


def looped(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], n=3
    )
    for choice in response.choices:
        print(choice.message.content)


def keyed(prompt):
    response = openai.Completion.create(model="gpt-3.5-turbo-instruct", prompt=prompt)
    return response.get("choices")
