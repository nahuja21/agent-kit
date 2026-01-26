# Project Summary Agent

AI-powered project folder analysis tool for Treya Partners.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."

# Run the console
python -m src
```

## Usage

1. Place a project folder in the `inputs/` directory
2. Run the console
3. Use `/file` to scan and analyze the project

### Commands

| Command | Description |
|---------|-------------|
| `/file` | Scan project folder and analyze with AI |
| `/status` | Show current configuration status |
| `/help` | Show available commands |
| `/quit` | Exit the console |

## Project Structure

```
new-agent/
├── inputs/          # Place project folders here
├── outputs/         # Analysis outputs saved here
├── src/
│   ├── __init__.py
│   ├── __main__.py  # Entry point
│   ├── config.py    # Configuration (env vars)
│   ├── console/     # Console interface
│   │   ├── app.py   # Main console application
│   ├── scanner/     # Directory scanning
│   │   ├── directory.py  # Phased directory scanner
│   ├── llm/         # OpenAI client
│   │   ├── client.py
│   └── prompts/     # Background knowledge
│       ├── context.py  # Phased prompt builder
└── requirements.txt
```

## Configuration

Set via environment variables:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key (required) |

Model is hardcoded in `src/config.py` (default: `gpt-4o`).

## Phased Architecture

The scanner and prompts are organized into phases for easy extension:

### Scanner Phases (`src/scanner/directory.py`)
- **Phase 1**: Structure & Hierarchy (implemented)
- **Phase 2**: Metadata (placeholder)
- **Phase 3**: Content Extraction (placeholder)
- **Phase 4**: Deep Analysis (placeholder)

### Prompt Phases (`src/prompts/context.py`)
- **Phase 1**: Company Background
- **Phase 2**: Project Structure
- **Phase 3**: Analysis Instructions
- **Phase 4**: Output Format

## Folder Conventions

Project folders typically contain:
- `Agreement/` - Contracts, SOWs
- `Assessment & Proposal/` - Initial assessments
- `Categories/` - Work by spend category
- `Project Updates/` - Status updates
- `Archive/` - (ignored) Old files
