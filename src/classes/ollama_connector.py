from ollama import Client
from dotenv import load_dotenv
import os

class OllamaConnector:

  def __init__(self,current_model: str):
    load_dotenv()
    ollama_host = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    self.model = current_model
    self.ollama = Client(
        host=ollama_host  
    )

  def embed_text(self, text):
    response = self.ollama.embed(model=self.model, input=text)
    return response.embeddings[0]
