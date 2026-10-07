import openai


def continue_text(prompt):
    response = openai.completions.create(
        model="gpt-3.5-turbo-instruct",
        prompt=prompt,
        max_tokens=64,
        stop=["\n\n"],
    )
    return response.choices[0].text.strip()
