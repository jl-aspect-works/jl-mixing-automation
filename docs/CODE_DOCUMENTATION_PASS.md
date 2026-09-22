# Code Documentation Notes

## Purpose

This revision adds explanatory comments to the implementation without
changing its public behavior. Comments focus on:

- File and module responsibilities
- Public function contracts
- Command workflow phases
- Transactional rollback and deletion safety
- macOS/Linux portability decisions
- JSON and Markdown ownership boundaries
- Test fixture and assertion intent
- CI and Makefile responsibilities

The approved recursive-delete hardening for `create-delivery` is also included.

Comments intentionally avoid narrating obvious shell syntax line by line.
