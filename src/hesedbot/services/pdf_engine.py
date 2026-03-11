import os
from hesedbot.config import Config, CSS_STYLE
from hesedbot.utils import LessonNoteGenerator, generate_pdf

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

def generate_filename(
        subject: str, school_class: str, topic: str, duration: str, week: int, term: str
        ) -> str:
    # Generate content
    try:
        lesson_note_generator = LessonNoteGenerator()
        lesson_note = lesson_note_generator.generate(
            subject=subject, 
            school_class=school_class, 
            topic=topic,
            duration=duration, 
            week=week, 
            term=term
        )
        # Checks if lesson_note is None before proceeding to PDF generation
        if not lesson_note:
            raise Exception("Error: The AI failed to generate content after multiple attempts.")
        # generate_pdf returns the filename (e.g., "math_jss3_2024.pdf")  
        filename = generate_pdf(note=lesson_note, subject=subject, CSS_STYLE=CSS_STYLE, 
                                path=str(Config.UPLOAD_FOLDER))
        return filename
    except Exception as e:
        # We return the error as a string so the LangGraph agent can read it
        raise Exception(f"System Error during PDF generation: {str(e)}")