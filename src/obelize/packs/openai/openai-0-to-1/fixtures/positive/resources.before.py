import openai


def variation(path):
    return openai.Image.create_variation(image=open(path, "rb"), n=1)


def models():
    return openai.Model.list()


def upload(path):
    return openai.File.create(file=open(path, "rb"), purpose="fine-tune")
