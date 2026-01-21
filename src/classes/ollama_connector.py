from ollama import Client
from dotenv import load_dotenv
import os

class OllamaConnector:  
  load_dotenv()
  ollama_host = os.getenv('OLLAMA_URL', 'http://localhost:11434')

  model = os.getenv('MODEL_NAME')
  ollama = Client(
      host=ollama_host  
  )
  
  @classmethod
  def embed_text(cls, text):
    response = cls.ollama.embed(model=cls.model, input=text)
    return response.embeddings[0]
