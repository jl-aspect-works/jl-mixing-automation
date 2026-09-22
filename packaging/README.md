# Packaging

`requirements.txt` pins the JSON Schema validator installed into the
application-private virtual environment. `RELEASE_README.md` becomes the root
README in end-user archives. Release construction and verification are handled
by `tools/build-release`, `tools/verify-release-archive`, and
`tools/release-check`.
