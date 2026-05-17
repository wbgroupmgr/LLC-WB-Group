# Claude Setup / Guide



## Multi-User/Subscription configuration

- a common issue when switching between different Claude accounts (w/ differnt subscriptions) on the same machine.
- ~/.claude directory is tied to whichever account was first used on that system.
- You can fix this by using a separate configuration directory for your Pro account.

### Cmd Line Claude

- The ~/.claude directory issue mainly affects Claude Code (the terminal version)
    - not Claude Desktop's account switching functionality.
- Quick fix: Set the CLAUDE_CONFIG_DIR environment variable to use a different directory for your Pro account.
- You can create an alias like:
        ````alias claude-pro='CLAUDE_CONFIG_DIR=~/.claude-free claude'````
- `claude-free` uses ~/.claude-free (linked to frankr6591@gmail.com)
- `claude` uses ~/.claude (for wbgroupmgr@gmail.com)


### Claude Desktop specifically:
- For Claude Desktop the settings are not in ~/.claude
- the account switching happens through the web interface.
- When you have `both personal and organization accounts` with the same email
    - you can switch between them by clicking your initials in the lower left corner
    - a blue checkmark shows which account is active.
- **The /cmd feature ONLY WORKS in claude/code**





