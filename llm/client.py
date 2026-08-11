from ollama import chat

class LLMclient():
    def __init__(self, model = "llama3.1", num_ctx = 3000):
        self.model = model
        self.num_ctx = num_ctx

    def generate(self, system_prompt, user_content):

        response = chat(
            model=self.model,
            messages =[{"role": "system", "content": system_prompt,
                                 "role": "user", "content": user_content
                        }],
            options= {"num_ctx": self.num_ctx}

            )

        messages = [{"role": "system", "content": system_prompt,
                     "role": "user", "content": user_content
                     }]

        return response.message.content


    