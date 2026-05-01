# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python 3.12+ project using `pyproject.toml` for dependency management. The project is currently in early development with a minimal starter structure.

## Development Environment

- Python version: 3.12+
- Virtual environment: `.venv/`
- Dependency file: `pyproject.toml`

## Common Commands

Activate the virtual environment before running commands:
```bash
.venv\Scripts\activate  # Windows
```

Install dependencies:
```bash
pip install -e .
```

Run the main script:
```bash
python main.py
```

## Project Structure

- `main.py` - Main entry point for the application
- `pyproject.toml` - Project configuration and dependencies
