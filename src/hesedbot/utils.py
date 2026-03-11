import time, openai
import markdown, re, os
from hesedbot.config import Config, METAPROMPT
from weasyprint import HTML, CSS
from datetime import datetime


class LessonNoteGenerator(object):
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.DEEPSEEK_API_URL)
        self.METAPROMPT = METAPROMPT
        
    def generate(self, subject: str, school_class: str, topic: str, duration: str, week: int, term: str) -> str | None:
        user_prompt = f"Generate a lesson note for {school_class} {subject} students on the topic: {topic} Duration: {duration} Week: {week} Term: {term} term"
        max_retries = 5
        delay = 2
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": self.METAPROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    stream=False
                )
                content = response.choices[0].message.content
                if content is not None:
                    return content
            except openai.APIConnectionError as e:
                #Handle connection errors (e.g., network issues, DeepSeek downtime)
                print(f"Failed to connect to OpenAI API: {e}") #In production this info will be logged instead of printed
                if attempt < max_retries:
                    print(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
            except Exception as e:
                raise Exception(f"Error generating lesson note: {str(e)}")
        return None
                


def generate_pdf(note: str, subject: str, CSS_STYLE: str, path: str) -> str:
    html_output = markdown.markdown(note)
    html = HTML(string=html_output)
    css = CSS(string=CSS_STYLE)
    note_title = '_'.join(subject.lower().split() + [datetime.now().strftime("%Y%m%d_%H%M%S")])
    save_dir = os.path.join(path, f'{note_title}.pdf')
    html.write_pdf(save_dir, stylesheets=[css]) 
    return f'{note_title}.pdf'