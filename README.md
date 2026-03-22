# kernel-build-mcp

MCP server for remote Linux kernel cross-compilation.

## Setup

### 1. Install Tailscale

Install on both Mac and Linux:

```bash
# Mac
brew install tailscale

# Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Enable Tailscale SSH on the Linux machine:

```bash
sudo tailscale up --ssh
```

Verify connectivity from Mac:

```bash
# Check Tailscale IP
tailscale ip -4   # on Linux machine

# Test SSH (no keys needed — Tailscale handles auth)
ssh user@100.x.x.x
```

Add to `~/.ssh/config` for convenience:

```
Host kernel-build
    HostName 100.x.x.x
    User <user>
```

### 2. Deploy MCP server to Linux

```bash
scp -r . kernel-build:~/kernel-build-mcp/
ssh kernel-build "~/kernel-build-mcp/install.sh"
```

### 3. Configure

Either edit config on Linux directly:

```bash
ssh kernel-build "vi ~/.config/kernel-build-mcp/config.json"
```

Or use the `set_config` tool from Claude Code after connecting.

### 4. Connect from Claude Code

Copy `.mcp.json` to your kernel project:

```bash
cp .mcp.json /path/to/SmokeR24.1-kernel/.mcp.json
```

Or merge with existing `.mcp.json` if one exists.

Verify: `claude --mcp-debug`

## Tools

| Tool | Description |
|------|-------------|
| `get_config` | Show current configuration |
| `set_config` | Update configuration remotely |
| `git_pull` | Fetch and pull latest changes |
| `git_reset` | Hard reset to remote state |
| `build` | Full kernel build |
| `build_module` | Build specific module directory |
| `make_defconfig` | Apply defconfig |
| `clean` | Clean build artifacts |
| `get_build_log` | Read last build log |
| `get_artifact` | Download build artifact (base64) |
| `run_command` | Run arbitrary command in kernel dir |
