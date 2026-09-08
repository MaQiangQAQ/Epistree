# Project-local Zhihu tooling

- For every Zhihu Skill or `zhihu-cli` operation in this project, set
  `ZHIHU_CLI_HOME=/Users/lvpeiye/Study/Project/20260901-知乎黑客松/.zhihu-cli`.
- Invoke the project binary by its absolute path:
  `/Users/lvpeiye/Study/Project/20260901-知乎黑客松/.zhihu-cli/current/zhihu-cli`.
- Do not use or install a global `zhihu-cli`, and do not modify `PATH` for it.
- Keep authentication project-scoped: inject `ZHIHU_ACCESS_SECRET` only into the
  process that needs it. Do not run `auth set`, because it stores the secret in
  the operating-system keychain and would not be project-local.

