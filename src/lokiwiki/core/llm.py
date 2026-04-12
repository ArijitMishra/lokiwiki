import json
import re
import ollama
from rich.console import Console
console = Console()

INGEST_PROMPT_TEMPLATE = """You are a disciplined wiki maintainer. Your job is to read a source document and integrate its knowledge into an existing wiki.

## Current Wiki Index
{index}

## Source Document
Filename: {filename}
Content:
{source_text}

## Your Task
Analyze this source and return a JSON object with the following structure:

{{
  "pages": [
    {{
      "filename": "Concepts/Topic_Name.md",
      "frontmatter": {{
        "title": "Topic Name",
        "tags": ["tag1", "tag2"],
        "created": "{date}",
        "updated": "{date}",
        "sources": ["raw/{filename}"],
        "related": ["[[Related Topic]]"]
      }},
      "content": "Full markdown body here using [[Wikilinks]] for internal references."
    }}
  ],
  "index_update": "Full updated index.md content",
  "log_entry": "## [{date}] ingest | {filename}\\n\\nBrief summary.",
  "contradictions": []
}}

## Strict Rules
- Return ONLY the JSON object. No explanation, no markdown fences, no preamble.
- Do NOT include newlines inside JSON string values. Use \\n for line breaks within strings.
- All string values must be valid JSON — escape any special characters.
- Keep page content concise — aim for 200-400 words per page.
- Create 3-6 pages maximum per ingest.
"""

QUERY_PROMPT_TEMPLATE = """You are a knowledgeable wiki assistant. Answer the user's question using only the wiki pages provided.

## Wiki Pages
{pages_content}

## Question
{question}

## Instructions
- Answer clearly and concisely using information from the wiki pages above.
- Cite your sources using [[Wikilink]] format when referencing specific pages.
- If the answer requires information not present in the wiki, say so explicitly.
- At the end, list which pages you used under a ## Sources section.
- Return a JSON object with this structure:

{{
  "answer": "Your full markdown answer here, using [[Wikilinks]] for citations.",
  "sources": ["Concepts/Page_One.md", "Concepts/Page_Two.md"],
  "save_as": "Suggested_Filename.md"
}}

Return ONLY the JSON. No preamble, no markdown fences.
"""

RELEVANCE_PROMPT_TEMPLATE = """You are a wiki search assistant. Given an index of wiki pages and a question, return the filenames of the most relevant pages.

## Wiki Index
{index}

## Question
{question}

## Instructions
- Return the filenames of pages most likely to help answer the question.
- If no pages are a perfect match, return the ones that are closest in topic.
- Always return at least 1 page unless the index is completely empty.
- Maximum 5 pages.

Return a JSON array of filenames. Example:
["Concepts/Attention.md", "Sources/Paper.md"]

Return ONLY the JSON array. No explanation.
"""

def _clean_llm_output(raw: str) -> str:
    """
    Clean common LLM output issues before JSON parsing.
    """
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Remove first line (```json or ```) and last line (```)
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Find the JSON object — start at first { and end at last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end+1]

    # Replace literal control characters inside strings
    # This handles the "Invalid control character" error
    def fix_control_chars(s):
        # Replace actual newlines/tabs inside string values with escaped versions
        result = []
        in_string = False
        escape_next = False
        for char in s:
            if escape_next:
                result.append(char)
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                result.append(char)
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                result.append(char)
                continue
            if in_string and char == '\n':
                result.append('\\n')
                continue
            if in_string and char == '\r':
                result.append('\\r')
                continue
            if in_string and char == '\t':
                result.append('\\t')
                continue
            result.append(char)
        return ''.join(result)

    raw = fix_control_chars(raw)
    return raw


class LLM:
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = model

    def ingest(self, source_text: str, filename: str, index: str, date: str) -> dict:
        # Truncate source text to fit context window
        max_chars = 10000  # slightly smaller to leave room for prompt + output
        if len(source_text) > max_chars:
            source_text = source_text[:max_chars] + "\n\n[...truncated...]"

        prompt = INGEST_PROMPT_TEMPLATE.format(
            index=index,
            source_text=source_text,
            filename=filename,
            date=date,
        )

        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={
                "temperature": 0,
                "num_predict": 3000,  # limit output length
            },
        )

        raw = response["message"]["content"]

        try:
            cleaned = _clean_llm_output(raw)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Save the raw output for debugging
            with open("llm_raw_output.txt", "w") as f:
                f.write(raw)
            raise ValueError(
                f"LLM returned invalid JSON: {e}\n"
                f"Raw output saved to llm_raw_output.txt for inspection."
            )

    def find_relevant_pages(self, index: str, question: str) -> list[str]:
            """Ask the LLM which pages in the index are relevant to the question."""
            prompt = RELEVANCE_PROMPT_TEMPLATE.format(index=index, question=question)
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0},
            )
            raw = response["message"]["content"]
            cleaned = _clean_llm_output(raw)
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1:
                result = json.loads(cleaned[start:end+1])
                if result:  # only return if non-empty
                    return result

            #return []
            #Fallback: extract all filenames directly from the index
            import re
            filenames = re.findall(r'\(([^)]+\.md)\)', index)
            console.print("No relevent pages found, return 5 files")
            return filenames[:5]  # cap at 5

    def query(self, question: str, pages_content: str) -> dict:
        """Answer a question using the provided wiki page content."""
        prompt = QUERY_PROMPT_TEMPLATE.format(
            question=question,
            pages_content=pages_content,
        )
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 2000},
        )
        raw = _clean_llm_output(response["message"]["content"])
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            with open("llm_query_raw.txt", "w") as f:
                f.write(response["message"]["content"])
            raise ValueError(f"LLM returned invalid JSON: {e}\nRaw output saved to llm_query_raw.txt")