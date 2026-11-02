# Third-party software and provenance

## jsonschema 4.25.1

- Upstream: https://github.com/python-jsonschema/jsonschema
- Exact release license: https://github.com/python-jsonschema/jsonschema/blob/v4.25.1/COPYING
- License: MIT
- Use: installed dependency providing `Draft202012Validator`. No validator source files were copied or modified.
- License checked on 2 November 2026. The notice is reproduced below. The application license does not replace dependencies' licenses.

```text
Copyright (c) 2013 Julian Berman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Transitive dependencies

The installation resolves attrs, jsonschema-specifications, referencing, rpds-py and typing-extensions as required by the validator and Python version. Their distributions retain their own licenses; this repository does not vendor their source or wheels. `requirements-tested.txt` records the tested versions. Inspect each distribution's license before bundling or redistributing packages.

## New application code

The CRM policy, review/export workflow, fixtures and tests were generated with Codex for this portfolio. This repository is not a fork of jsonschema and does not claim authorship of that library.
