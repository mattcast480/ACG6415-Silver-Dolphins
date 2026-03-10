# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository is in early initialization — no source files have been committed yet. Update this file once the project structure is established.

## Project Overview

*(Add a description of what this project does once files are added.)*

## Commands

*(Add build, lint, and test commands here once the project is set up.)*
- At the start of every new session, automatically run `git pull origin master` to ensure local files are up to date with the GitHub remote.
- After completing each major development milestone, ask the user: "Do you want to continue to the next task, or are you ending the session?" If the user indicates they are ending the session, remind them to commit all changes and push to GitHub, and suggest an appropriate version tag and commit message summarizing what was built during the session.
- Maintain a CHANGELOG.md file
- Present options and ask clarifying questions - do not automate all decisions
- Use descriptive names for all functions and variables
- When pushing to GitHub, always run git pull origin master before git push to avoid sync conflicts.
## Architecture

*(Add high-level architecture notes here once the codebase exists.)*

## Code Style

- Always include comments in code explaining what each section does.
- Write comments as if explaining to someone learning the code for the first time.
- Use Python as the programming language.
- Build for portability (requirements.txt, README, etc.)
- Do not suggest account numbers in undefined or gap ranges
