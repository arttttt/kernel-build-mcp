# kernel-build-mcp

MCP server for remote Linux kernel cross-compilation.

## Setup

### 1. Tailscale (networking)

Install on both Mac and Linux:

```bash
# Mac
brew install tailscale

# Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Note the Tailscale IP of the Linux machine (`tailscale ip -4`).

### 2. SSH key

```bash
# On Mac (if you don't have a key yet)
ssh-keygen -t ed25519

# Copy to Linux machine
ssh-copy-id user@100.x.x.x

# Add to ~/.ssh/config
cat >> ~/.ssh/config << 'EOF'
Host kernel-build
    HostName 100.x.x.x
    User <user>
    IdentityFile ~/.ssh/id_ed25519
EOF
```

### 3. Deploy MCP server to Linux

```bash
scp -r . kernel-build:~/kernel-build-mcp/
ssh kernel-build "~/kernel-build-mcp/install.sh"
```

### 4. Configure

Either edit config on Linux:
```bash
ssh kernel-build "vi ~/.config/kernel-build-mcp/config.json"
```

Or use the `set_config` tool from Claude Code after connecting.

### 5. Connect from Claude Code

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
