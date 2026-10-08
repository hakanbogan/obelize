import openai


def message_in_a_name(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    message = response["choices"][0]["message"]
    return message["role"], message["content"]


def choice_in_a_name(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    choice = response.choices[0]
    return choice.finish_reason, choice.message.content


def every_choice(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], n=2
    )
    return [choice["message"]["content"] for choice in response["choices"]]


def usage_in_a_name(prompt):
    response = openai.Completion.create(model="gpt-3.5-turbo-instruct", prompt=prompt)
    usage = response["usage"]
    return usage["prompt_tokens"], usage["total_tokens"]


def pictures(prompt):
    return [picture["url"] for picture in openai.Image.create(prompt=prompt, n=2)["data"]]


def verdict(prompt):
    result = openai.Moderation.create(input=prompt)["results"][0]
    return result["flagged"]
