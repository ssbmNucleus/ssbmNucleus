# SSBM Nucleus 0.9.1

- **Fix**: model imports work on a Windows that writes decimals with a comma
  (German, French, Spanish, Portuguese and other number formats). On 0.9.0 they
  stopped while getting the fighters ready with "could not convert string to
  float". An import that failed this way works again after the update, with
  nothing to delete.

Windows only: macOS and Linux never had this bug and stay on 0.9.0.

Full changelog: https://github.com/ssbmNucleus/ssbmNucleus/blob/main/CHANGELOG.md
