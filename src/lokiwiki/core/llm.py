import json
import re
import ollama
from rich.console import Console
console = Console()

INGEST_PROMPT_TEMPLATE = """You are a disciplined wiki maintainer processing one chunk of a larger document.

## Current Wiki Index
{index}

## Source Document
Filename: {filename}
Chunk: {chunk_num} of {total_chunks}

Content:
{source_text}

## Your Task
Read this chunk and integrate its knowledge into the wiki.

IMPORTANT RULES:
- If a relevant page already exists in the index, UPDATE it — do not create a duplicate.
- Only CREATE a new page if no existing page covers this concept.
- Keep pages focused — one concept or entity per page.
- Use [[Wikilinks]] for all internal references.
- Every page MUST have YAML frontmatter.
- It is OK to return an empty "pages" list if this chunk adds nothing new.

Return a JSON object:
{{
  "pages": [
    {{
      "filename": "Concepts/Topic_Name.md",
      "action": "create",
      "frontmatter": {{
        "title": "Topic Name",
        "tags": ["tag1", "tag2"],
        "created": "{date}",
        "updated": "{date}",
        "sources": ["raw/{filename}"],
        "related": ["[[Related Topic]]"]
      }},
      "content": "Full markdown body using [[Wikilinks]]..."
    }}
  ],
  "index_update": "Full updated index.md content (preserve existing entries, add new ones)",
  "log_entry": "## [{date}] ingest chunk {chunk_num}/{total_chunks} | {filename}\\n\\nBrief summary.",
  "contradictions": []
}}

For the "action" field use "create" for new pages or "update" for existing ones.
Return ONLY the JSON. No preamble, no fences.
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

LINT_PROMPT_TEMPLATE = """You are a wiki health advisor. Review this wiki health report and suggest improvements.

## Wiki Health Report
{report_text}

## Wiki Index
{index}

## Your Task
Based on the issues above, suggest:
1. Which broken wikilinks could be fixed by linking to existing pages
2. Which orphan pages should be linked from other pages
3. Which concepts mentioned across pages deserve their own dedicated page
4. Any other improvements to make the wiki more connected and useful

Be specific and actionable. Keep suggestions concise.
Return your suggestions as plain markdown text, not JSON.
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

    def ingest(self, source_text: str, filename: str, index: str, date: str,
               chunk_num: int = 1, total_chunks: int = 1) -> dict:
        """Send one chunk to the LLM and get back structured wiki updates."""
        max_chars = 3000
        if len(source_text) > max_chars:
            source_text = source_text[:max_chars] + "\n\n[...truncated...]"

        prompt = INGEST_PROMPT_TEMPLATE.format(
            index=index,
            source_text=source_text,
            filename=filename,
            date=date,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
        )

        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 3000},
        )

        raw = response["message"]["content"]
        try:
            cleaned = _clean_llm_output(raw)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            with open("llm_raw_output.txt", "w") as f:
                f.write(raw)
            raise ValueError(
                f"LLM returned invalid JSON: {e}\n"
                f"Raw output saved to llm_raw_output.txt"
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

    def lint_suggestions(self, report_text: str, index: str) -> str:
            """Get LLM suggestions based on lint report."""
            prompt = LINT_PROMPT_TEMPLATE.format(
                report_text=report_text,
                index=index,
            )
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0, "num_predict": 1500},
            )
            return response["message"]["content"].strip()