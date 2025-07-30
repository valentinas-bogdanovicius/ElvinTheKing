"""
This utility is a derivative of the 'md-to-jira' script created by eshack94.
Original project: https://github.com/eshack94/md-to-jira
The code has been adapted to be used as a library within this project.

The MIT License (MIT)

Copyright (c) 2024 eshack94

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import re

def convert_to_jira_wiki(markdown_text):
    """
    Converts a markdown string to Jira wiki markup.
    """
    # Fenced code blocks
    markdown_text = re.sub(r'```(.*?)\n(.*?)\n```', r'{code:\1}\n\2\n{code}', markdown_text, flags=re.DOTALL)

    # Headers
    markdown_text = re.sub(r'^# (.*)$', r'h1. \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^## (.*)$', r'h2. \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^### (.*)$', r'h3. \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^#### (.*)$', r'h4. \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^##### (.*)$', r'h5. \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^###### (.*)$', r'h6. \1', markdown_text, flags=re.MULTILINE)

    # Bold
    markdown_text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', markdown_text)
    markdown_text = re.sub(r'__(.*?)__', r'*\1*', markdown_text)

    # Italic
    markdown_text = re.sub(r'\*(.*?)\*', r'_\1_', markdown_text)
    markdown_text = re.sub(r'_(.*?)_', r'_\1_', markdown_text)

    # Strikethrough
    markdown_text = re.sub(r'~~(.*?)~~', r'-\1-', markdown_text)

    # Unordered lists
    markdown_text = re.sub(r'^\* (.*)$', r'* \1', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^- (.*)$', r'- \1', markdown_text, flags=re.MULTILINE)
    
    # Inline code
    markdown_text = re.sub(r'`(.*?)`', r'{{\1}}', markdown_text)
    
    # Links
    markdown_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'[\1|\2]', markdown_text)
    
    return markdown_text
