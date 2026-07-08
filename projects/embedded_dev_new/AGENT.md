# AGENT

## Terminal Collaboration Rule

- The user keeps two separate terminals open:
  - one WSL terminal
  - one SSH terminal connected to the development board
- For all future operations requested in this workspace, actions performed from the WSL side must remain in the WSL terminal context.
- Do not switch to, take over, or assume use of the board's SSH terminal unless the user explicitly asks to operate there.
